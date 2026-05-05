// Chapter Timeline module
let chapters = [];
let currentChapterId = null;

function renderChapterTimeline(chapterList, containerId) {
    chapters = chapterList;
    const container = document.getElementById(containerId || 'chapter-list');
    container.innerHTML = '';

    if (!chapters || chapters.length === 0) {
        container.innerHTML = '<div style="padding:12px;color:#555;font-size:13px;">暂无章节数据</div>';
        return;
    }

    chapters.forEach((ch, idx) => {
        const item = document.createElement('div');
        item.className = 'chapter-item' + (ch.id === currentChapterId ? ' active' : '');
        item.dataset.chapterId = ch.id;
        item.innerHTML = `
            <div class="chapter-index">第${ch.index + 1}章</div>
            <div class="chapter-title">${ch.title}</div>
            <div class="chapter-summary">${ch.summary || ''}</div>
        `;
        item.addEventListener('click', () => selectChapter(ch.id));
        container.appendChild(item);
    });

    // Auto-select first chapter after layout settles (so graph container has dimensions)
    if (!currentChapterId && chapters.length > 0) {
        setTimeout(() => selectChapter(chapters[0].id), 100);
    }
}

function selectChapter(chapterId) {
    currentChapterId = chapterId;

    // Update UI
    document.querySelectorAll('.chapter-item').forEach(item => {
        item.classList.toggle('active', item.dataset.chapterId === chapterId);
    });

    // Trigger chapter change event
    if (typeof onChapterChange === 'function') {
        onChapterChange(chapterId);
    }
}

function getCurrentChapterId() {
    return currentChapterId;
}

function getChapterById(chapterId) {
    return chapters.find(ch => ch.id === chapterId);
}
