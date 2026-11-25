import {api,setAccessToken} from './api-client.js';
export async function login(email,password){const r=await api('/api/auth/login',{method:'POST',body:JSON.stringify({email,password})});setAccessToken(r.access_token);return r;}
export async function register(email,password){const r=await api('/api/auth/register',{method:'POST',body:JSON.stringify({email,password})});setAccessToken(r.access_token);return r;}
