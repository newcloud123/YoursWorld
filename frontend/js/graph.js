// Graph visualization using vis.js (dark theme, chapter-aware)
let network = null;

function renderGraph(containerId, graphData) {
    const container = document.getElementById(containerId);

    if (!graphData.nodes || graphData.nodes.length === 0) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#555;font-size:14px;">本章暂无人物关系数据</div>';
        return;
    }

    container.innerHTML = '';

    if (typeof vis === 'undefined') {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#c00;font-size:14px;">vis.js 加载失败</div>';
        return;
    }

    const nodes = new vis.DataSet(graphData.nodes.map(n => ({
        ...n,
        shape: 'dot',
        size: 28,
        font: { size: 13, color: '#c0c0d0', face: 'PingFang SC, Microsoft YaHei, sans-serif' },
        color: {
            background: '#ff6b35',
            border: '#e55a28',
            highlight: { background: '#ff8c5a', border: '#ffa726' },
            hover: { background: '#ff7b45', border: '#ffa726' },
        },
        borderWidth: 2,
    })));

    const edges = new vis.DataSet(graphData.edges.map(e => ({
        ...e,
        color: { color: '#3a3a5a', highlight: '#ff6b35', hover: '#5a5a8a' },
        font: { size: 10, color: '#666', strokeWidth: 0 },
        arrows: 'to',
        smooth: { type: 'curvedCW', roundness: 0.2 },
        width: 1,
    })));

    const options = {
        physics: {
            barnesHut: {
                gravitationalConstant: -3000,
                springLength: 150,
                springConstant: 0.04,
            },
            stabilization: { iterations: 100 },
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
        },
    };

    network = new vis.Network(container, { nodes, edges }, options);

    // Click event to highlight character in list
    network.on('click', function(params) {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            if (typeof highlightCharacter === 'function') {
                highlightCharacter(nodeId);
            }
        }
    });
}
