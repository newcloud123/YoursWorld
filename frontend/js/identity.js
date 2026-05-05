// Identity Selection module
let selectedIdentityMode = 'possess';
let selectedCharacterId = null;
let selectedSceneId = null;
let identityCharacters = [];
let identityScenes = [];

function openIdentityModal(novelId, chapterId) {
    const modal = document.getElementById('identity-modal');
    modal.classList.remove('hidden');

    // Set chapter info
    const ch = getChapterById(chapterId);
    document.getElementById('identity-chapter-info').textContent =
        ch ? `当前章节：${ch.title}` : '';

    // Reset state
    selectedCharacterId = null;
    selectedSceneId = null;
    selectedIdentityMode = 'possess';
    document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('.mode-tab[data-mode="possess"]').classList.add('active');
    document.getElementById('possess-panel').classList.remove('hidden');
    document.getElementById('custom-panel').classList.add('hidden');
    document.getElementById('possess-char-detail').classList.add('hidden');

    // Load characters and scenes
    loadIdentityData(novelId, chapterId);
}

async function loadIdentityData(novelId, chapterId) {
    try {
        const [charsResp, scenesResp] = await Promise.all([
            fetch(`/novel/${novelId}/characters?chapter_id=${chapterId}`),
            fetch(`/novel/${novelId}/scenes?chapter_id=${chapterId}`),
        ]);
        identityCharacters = await charsResp.json();
        identityScenes = await scenesResp.json();

        renderPossessList();
        renderSceneList();
    } catch (err) {
        console.error('Failed to load identity data:', err);
    }
}

function renderPossessList() {
    const container = document.getElementById('possess-char-list');
    container.innerHTML = '';

    identityCharacters.forEach(char => {
        const item = document.createElement('div');
        item.className = 'select-item' + (char.id === selectedCharacterId ? ' selected' : '');
        item.dataset.id = char.id;
        item.innerHTML = `
            <div class="item-name">${char.name}</div>
            <div class="item-desc">${(char.personality || '').substring(0, 50)}</div>
        `;
        item.addEventListener('click', () => {
            container.querySelectorAll('.select-item').forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            selectedCharacterId = char.id;
            showCharacterDetail(char);
        });
        container.appendChild(item);
    });
}

function showCharacterDetail(char) {
    const detail = document.getElementById('possess-char-detail');
    detail.classList.remove('hidden');
    document.getElementById('possess-char-name').textContent = char.name;

    const state = char.current_state || {};
    const info = document.getElementById('possess-char-info');
    info.innerHTML = `
        <div class="detail-field"><strong>性格：</strong>${char.personality || '未知'}</div>
        <div class="detail-field"><strong>背景：</strong>${char.background || '未知'}</div>
        <div class="detail-field"><strong>位置：</strong>${state.location || '未知'}</div>
        <div class="detail-field"><strong>状态：</strong>${state.status || '未知'}</div>
        <div class="detail-field"><strong>能力：</strong>${(state.abilities || []).join('、') || '凡人'}</div>
        <div class="detail-field"><strong>已知信息：</strong>${(state.knowledge || []).slice(0, 3).join('；') || '无'}</div>
    `;
}

function renderSceneList() {
    const container = document.getElementById('scene-list');
    container.innerHTML = '';

    if (identityScenes.length === 0) {
        container.innerHTML = '<div style="padding:8px;color:#555;font-size:13px;">本章暂无特定场景，将使用默认场景</div>';
        return;
    }

    identityScenes.forEach(scene => {
        const item = document.createElement('div');
        item.className = 'scene-item' + (scene.id === selectedSceneId ? ' selected' : '');
        item.innerHTML = `
            <div class="scene-name">${scene.name}</div>
            <div class="scene-meta">${scene.location || ''} | ${(scene.participants || []).join('、')}</div>
        `;
        item.addEventListener('click', () => {
            container.querySelectorAll('.scene-item').forEach(i => i.classList.remove('selected'));
            item.classList.add('selected');
            selectedSceneId = scene.id;
        });
        container.appendChild(item);
    });

    // Auto-select first scene
    if (identityScenes.length > 0 && !selectedSceneId) {
        selectedSceneId = identityScenes[0].id;
        container.querySelector('.scene-item').classList.add('selected');
    }
}

function closeIdentityModal() {
    document.getElementById('identity-modal').classList.add('hidden');
}

function setupIdentityModalListeners() {
    // Mode tabs
    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            selectedIdentityMode = tab.dataset.mode;
            document.getElementById('possess-panel').classList.toggle('hidden', selectedIdentityMode !== 'possess');
            document.getElementById('custom-panel').classList.toggle('hidden', selectedIdentityMode !== 'custom');
        });
    });

    // Cancel
    document.getElementById('identity-cancel').addEventListener('click', closeIdentityModal);
}

function getSelectedIdentity() {
    if (selectedIdentityMode === 'possess') {
        if (!selectedCharacterId) return null;
        return {
            mode: 'possess',
            character_id: selectedCharacterId,
        };
    } else {
        const name = document.getElementById('custom-name').value.trim();
        if (!name) return null;
        return {
            mode: 'custom',
            custom_name: name,
            custom_background: document.getElementById('custom-background').value.trim(),
            custom_abilities: document.getElementById('custom-abilities').value.trim()
                .split(',').map(s => s.trim()).filter(Boolean),
        };
    }
}
