import {api} from './api-client.js';
export const licenceStatus=()=>api('/api/licences/status');
export const activateTrial=()=>api('/api/licences/trial',{method:'POST',body:'{}'});
