// Character panel module - renders character cards with chapter-aware states
let allCharacters = [];

function renderCharacterList(characters, chapterId) {
    allCharacters = characters;
    const container = document.getElementById('character-list');
    container.innerHTML = '';

    if (!characters || characters.length === 0) {
        container.innerHTML = '<div style="padding:12px;color:#555;font-size:13px;">暂无人物数据</div>';
        return;
    }

    characters.forEach(char => {
        const card = document.createElement('div');
        card.className = 'char-card';
        card.id = `char-card-${char.id}`;

        const state = char.current_state || {};
        const stateHtml = buildStateHtml(state);

        card.innerHTML = `
            <div class="char-header">
                <span class="char-name">${char.name}</span>
                <span class="char-toggle">▼</span>
            </div>
            <div class="char-body">
                <div class="char-field">
                    <label>性格</label>
                    <p>${char.personality || '未知'}</p>
                </div>
                <div class="char-field">
                    <label>背景</label>
                    <p>${char.background || '未知'}</p>
                </div>
                ${stateHtml}
                ${buildRelationshipsHtml(char.relationships || [], char.name)}
            </div>
        `;

        // Toggle expand
        card.querySelector('.char-header').addEventListener('click', () => {
            const body = card.querySelector('.char-body');
            body.classList.toggle('expanded');
            card.querySelector('.char-toggle').textContent = body.classList.contains('expanded') ? '▲' : '▼';
        });

        container.appendChild(card);
    });
}

function buildStateHtml(state) {
    if (!state || Object.keys(state).length === 0) return '';

    return `
        <div class="char-state">
            ${state.location ? `<div class="char-state-item"><strong>位置：</strong>${state.location}</div>` : ''}
            ${state.status ? `<div class="char-state-item"><strong>状态：</strong>${state.status}</div>` : ''}
            ${state.abilities && state.abilities.length ? `<div class="char-state-item"><strong>能力：</strong>${state.abilities.join('、')}</div>` : ''}
            ${state.knowledge && state.knowledge.length ? `<div class="char-state-item"><strong>已知：</strong>${state.knowledge.slice(0, 3).join('；')}${state.knowledge.length > 3 ? '...' : ''}</div>` : ''}
        </div>
    `;
}

function buildRelationshipsHtml(relationships, charName) {
    if (!relationships || relationships.length === 0) return '';

    const relsHtml = relationships.map(rel => {
        const other = rel.source === charName ? rel.target : (rel.target === charName ? rel.source : rel.target);
        return `<div class="char-rel">与${other}：${rel.relation || ''}</div>`;
    }).join('');

    return `
        <div class="char-field">
            <label>人际关系</label>
            ${relsHtml}
        </div>
    `;
}

function highlightCharacter(charId) {
    // Remove previous highlights
    document.querySelectorAll('.char-card.highlighted').forEach(c => c.classList.remove('highlighted'));

    const card = document.getElementById(`char-card-${charId}`);
    if (card) {
        card.classList.add('highlighted');
        // Expand and scroll to it
        const body = card.querySelector('.char-body');
        body.classList.add('expanded');
        card.querySelector('.char-toggle').textContent = '▲';
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}
