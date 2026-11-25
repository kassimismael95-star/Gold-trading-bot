import {api} from './api-client.js';
export async function checkout(plan_code){return api('/api/payments/checkout',{method:'POST',body:JSON.stringify({plan_code})});}
export async function verifyPayment(tx_ref,transaction_id){return api('/api/payments/verify',{method:'POST',body:JSON.stringify({tx_ref,transaction_id})});}
