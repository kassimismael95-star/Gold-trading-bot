export function showNotice(message,kind='info'){
 const node=document.createElement('div'); node.setAttribute('role','status'); node.dataset.kind=kind;
 node.textContent=String(message); document.body.appendChild(node); setTimeout(()=>node.remove(),5000);
}
