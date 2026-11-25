import {api} from './api-client.js';
export const listAccounts=()=>api('/api/accounts');
export const addAccount=payload=>api('/api/accounts',{method:'POST',body:JSON.stringify(payload)});
export const accountCommand=(id,command)=>api(`/api/accounts/${id}/commands`,{method:'POST',body:JSON.stringify({command})});
