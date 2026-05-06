// Game Chat module - supports GM, NPC, narrator, player, and system messages
let currentSessionId = null;
let currentPlayerName = '';

function initGameChat(sessionId, playerName, subtitle) {
    currentSessionId = sessionId;
    currentPlayerName = playerName;

    document.getElementById('chat-title').textContent = `${playerName} 的冒险`;
    document.getElementById('chat-subtitle').textContent = subtitle || '';
    document.getElementById('chat-messages').innerHTML = '';
    document.getElementById('chat-panel').classList.remove('hidden');
}

function addMessage(type, speaker, content) {
    const container = document.getElementById('chat-messages');
    const msg = document.createElement('div');
    msg.className = `msg ${type}`;

    let nameHtml = '';
    if (type === 'narrator') {
        nameHtml = '<div class="msg-name narrator-label">旁白</div>';
    } else if (type === 'npc') {
        nameHtml = `<div class="msg-name">${speaker}</div>`;
    } else if (type === 'player') {
        nameHtml = `<div class="msg-name">${speaker}</div>`;
    } else if (type === 'gm') {
        nameHtml = `<div class="msg-name">GM</div>`;
    }

    msg.innerHTML = `
        <div>
            ${nameHtml}
            <div class="msg-bubble">${formatContent(content)}</div>
        </div>
    `;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

function addWarningMessage(content) {
    const container = document.getElementById('chat-messages');
    const msg = document.createElement('div');
    msg.className = 'msg gm warning';
    msg.innerHTML = `
        <div>
            <div class="msg-name">GM 提示</div>
            <div class="msg-bubble">${formatContent(content)}</div>
        </div>
    `;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

function formatContent(text) {
    if (!text) return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/「(.*?)」/g, '<em>「$1」</em>');
}

async function sendGameMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message || !currentSessionId) return;

    // Show player message immediately
    addMessage('player', currentPlayerName, message);
    input.value = '';

    const sendBtn = document.getElementById('chat-send');

    // Show loading state
    sendBtn.disabled = true;
    input.disabled = true;
    sendBtn.innerHTML = '<span class="spinner"></span>';

    // Show a "thinking" placeholder
    const thinkingId = 'thinking-' + Date.now();
    const container = document.getElementById('chat-messages');
    const thinkingEl = document.createElement('div');
    thinkingEl.id = thinkingId;
    thinkingEl.className = 'msg gm thinking';
    thinkingEl.innerHTML = `
        <div>
            <div class="msg-name">GM</div>
            <div class="msg-bubble"><span class="spinner"></span> 世界运转中...</div>
        </div>
    `;
    container.appendChild(thinkingEl);
    container.scrollTop = container.scrollHeight;

    try {
        const resp = await fetch(`/game/${currentSessionId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });

        // Remove thinking placeholder
        const el = document.getElementById(thinkingId);
        if (el) el.remove();

        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }

        const data = await resp.json();

        // Render all returned messages
        (data.messages || []).forEach(msg => {
            if (msg.type === 'player') {
                // Already shown above, skip duplicate
            } else if (msg.type === 'gm') {
                if (msg.content && msg.content.includes('⚠')) {
                    addWarningMessage(msg.content);
                } else {
                    addMessage('gm', msg.speaker || 'GM', msg.content);
                }
            } else if (msg.type === 'narrator') {
                addMessage('narrator', msg.speaker || '旁白', msg.content);
            } else if (msg.type === 'npc') {
                addMessage('npc', msg.speaker, msg.content);
            } else if (msg.type === 'system') {
                addMessage('system', '', msg.content);
            }
        });
    } catch (err) {
        // Remove thinking placeholder on error too
        const el = document.getElementById(thinkingId);
        if (el) el.remove();
        addMessage('system', '', `发送失败：${err.message}`);
    } finally {
        sendBtn.disabled = false;
        input.disabled = false;
        sendBtn.textContent = '行动';
        input.focus();
    }
}

function closeGameChat() {
    document.getElementById('chat-panel').classList.add('hidden');
    document.getElementById('memory-panel').classList.add('hidden');
    if (currentSessionId) {
        fetch(`/game/${currentSessionId}`, { method: 'DELETE' });
        currentSessionId = null;
    }
}

function loadMemoryPanel(novelId, characterName, chapterId) {
    const content = document.getElementById('memory-content');
    content.innerHTML = '<p style="color:#666;">加载中...</p>';

    fetch(`/novel/${novelId}/characters?chapter_id=${chapterId}`)
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        })
        .then(characters => {
            if (!Array.isArray(characters) || characters.length === 0) {
                content.innerHTML = '<p style="color:#666;">暂无人物数据</p>';
                return;
            }
            const char = characters.find(c => c.name === characterName);
            if (!char) {
                content.innerHTML = `<p style="color:#666;">未找到角色「${characterName}」</p>`;
                return;
            }
            const state = char.current_state || {};
            const rels = state.relationships || {};
            const relEntries = typeof rels === 'object' && !Array.isArray(rels) ? Object.entries(rels) : [];
            content.innerHTML = `
                <div class="memory-section">
                    <h4>性格</h4>
                    <p>${char.personality || '未知'}</p>
                </div>
                <div class="memory-section">
                    <h4>背景</h4>
                    <p>${char.background || '未知'}</p>
                </div>
                <div class="memory-section">
                    <h4>当前位置</h4>
                    <p>${state.location || '未知'}</p>
                </div>
                <div class="memory-section">
                    <h4>身份状态</h4>
                    <p>${state.status || '未知'}</p>
                </div>
                <div class="memory-section">
                    <h4>能力</h4>
                    <ul>${(state.abilities || []).map(a => `<li>${a}</li>`).join('') || '<li>无</li>'}</ul>
                </div>
                <div class="memory-section">
                    <h4>已知信息</h4>
                    <ul>${(state.knowledge || []).map(k => `<li>${k}</li>`).join('') || '<li>无</li>'}</ul>
                </div>
                <div class="memory-section">
                    <h4>人际关系</h4>
                    <ul>${relEntries.map(([k, v]) => `<li>${k}：${v}</li>`).join('') || '<li>无</li>'}</ul>
                </div>
            `;
        })
        .catch(err => {
            content.innerHTML = `<p style="color:#c00;">加载失败：${err.message}</p>`;
        });
}
