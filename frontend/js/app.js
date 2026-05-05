// Main application logic - orchestrates all modules
let currentNovelId = null;

// === Initialization ===
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadNovelList();
});

function setupEventListeners() {
    // Upload handlers
    document.getElementById('novel-file').addEventListener('change', handleUpload);
    document.getElementById('novel-file-welcome').addEventListener('change', handleUpload);

    // Novel selector
    document.getElementById('novel-select').addEventListener('change', (e) => {
        if (e.target.value) {
            loadNovel(e.target.value);
        }
    });

    // Identity modal
    setupIdentityModalListeners();
    document.getElementById('identity-confirm').addEventListener('click', startGame);

    // Chat
    document.getElementById('chat-send').addEventListener('click', sendGameMessage);
    document.getElementById('chat-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendGameMessage();
    });
    document.getElementById('chat-close').addEventListener('click', closeGameChat);

    // Memory panel
    document.getElementById('chat-memory-btn').addEventListener('click', toggleMemoryPanel);
    document.getElementById('memory-close').addEventListener('click', () => {
        document.getElementById('memory-panel').classList.add('hidden');
    });
}

// === Novel Management ===
async function loadNovelList() {
    try {
        const resp = await fetch('/novels');
        const novels = await resp.json();

        // Populate dropdown
        const select = document.getElementById('novel-select');
        select.innerHTML = '<option value="">选择小说...</option>';
        novels.forEach(n => {
            const opt = document.createElement('option');
            opt.value = n.novel_id;
            opt.textContent = `${n.novel_id} (${n.chapters_count}章, ${n.characters_count}人)`;
            select.appendChild(opt);
        });

        // Populate welcome screen list
        if (novels.length > 0) {
            const novelList = document.getElementById('novel-list');
            novelList.innerHTML = '';
            document.getElementById('existing-novels').classList.remove('hidden');
            novels.forEach(n => {
                const item = document.createElement('div');
                item.className = 'novel-item';
                item.innerHTML = `
                    <div class="novel-name">${n.novel_id}</div>
                    <div class="novel-meta">${n.chapters_count} 章 · ${n.characters_count} 个人物</div>
                `;
                item.addEventListener('click', () => loadNovel(n.novel_id));
                novelList.appendChild(item);
            });
        }
    } catch (err) {
        console.error('Failed to load novels:', err);
    }
}

async function loadNovel(novelId) {
    currentNovelId = novelId;

    // Update selector
    document.getElementById('novel-select').value = novelId;

    // Show main content, hide welcome
    document.getElementById('welcome-screen').classList.add('hidden');
    document.getElementById('main-content').classList.remove('hidden');

    // Load chapters
    try {
        const chaptersResp = await fetch(`/novel/${novelId}/chapters`);
        const chaptersData = await chaptersResp.json();
        renderChapterTimeline(chaptersData);
    } catch (err) {
        console.error('Failed to load chapters:', err);
    }
}

// === Chapter Change ===
async function onChapterChange(chapterId) {
    if (!currentNovelId) return;

    // Reload characters and graph for this chapter
    try {
        const [charsResp, graphResp] = await Promise.all([
            fetch(`/novel/${currentNovelId}/characters?chapter_id=${chapterId}`),
            fetch(`/novel/${currentNovelId}/graph?chapter_id=${chapterId}`),
        ]);

        const characters = await charsResp.json();
        const graphData = await graphResp.json();

        renderCharacterList(characters, chapterId);
        // Delay graph render to ensure container has computed dimensions
        setTimeout(() => {
            renderGraph('graph-container', graphData);
        }, 100);
    } catch (err) {
        console.error('Failed to load chapter data:', err);
    }
}

// === Upload ===
async function handleUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const progressDiv = document.getElementById('upload-progress');
    const progressText = document.getElementById('progress-text');
    progressDiv.classList.remove('hidden');
    progressText.textContent = '正在上传并提取人物信息，这可能需要几分钟...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch('/novel/upload', { method: 'POST', body: formData });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || '上传失败');
        }

        const data = await resp.json();
        progressText.textContent = `提取完成！${data.chapters_count} 章，${data.characters_count} 个人物，${data.scenes_count} 个场景`;

        setTimeout(() => {
            progressDiv.classList.add('hidden');
            loadNovelList();
            loadNovel(data.novel_id);
        }, 2000);
    } catch (err) {
        progressText.textContent = '上传失败: ' + err.message;
        setTimeout(() => progressDiv.classList.add('hidden'), 3000);
    }

    // Reset file input
    e.target.value = '';
}

// === Identity & Game Start ===
function openIdentitySelection() {
    const chapterId = getCurrentChapterId();
    if (!chapterId || !currentNovelId) {
        alert('请先选择章节');
        return;
    }
    openIdentityModal(currentNovelId, chapterId);
}

async function startGame() {
    const identity = getSelectedIdentity();
    if (!identity) {
        alert('请选择一个角色或输入身份信息');
        return;
    }

    const chapterId = getCurrentChapterId();
    const sceneId = getSelectedSceneId();

    const body = {
        novel_id: currentNovelId,
        chapter_id: chapterId,
        player_identity: identity,
        scene_id: sceneId,
    };

    try {
        const resp = await fetch('/game/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || '启动失败');
        }

        const data = await resp.json();
        closeIdentityModal();

        // Initialize game chat
        const subtitle = `第${(getChapterById(chapterId)?.index || 0) + 1}章 · ${getChapterById(chapterId)?.title || ''}`;
        initGameChat(data.session_id, data.player_name, subtitle);

        // Show opening narrative
        if (data.opening_narrative) {
            addMessage('gm', 'GM', data.opening_narrative);
        }
    } catch (err) {
        alert('启动游戏失败: ' + err.message);
    }
}

// === Memory Panel ===
function toggleMemoryPanel() {
    const panel = document.getElementById('memory-panel');
    if (panel.classList.contains('hidden')) {
        // Show panel first, then load data
        panel.classList.remove('hidden');

        const chapterId = getCurrentChapterId();
        const title = document.getElementById('chat-title').textContent;
        const playerName = title.replace(' 的冒险', '').trim();

        if (!currentNovelId || !playerName) {
            document.getElementById('memory-content').innerHTML =
                '<p style="color:#666;">无法加载：缺少小说或角色信息</p>';
            return;
        }
        loadMemoryPanel(currentNovelId, playerName, chapterId);
    } else {
        panel.classList.add('hidden');
    }
}
