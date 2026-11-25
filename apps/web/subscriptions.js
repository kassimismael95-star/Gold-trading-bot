import {api} from './api-client.js';
export const subscriptionStatus=()=>api('/api/subscriptions/status');
