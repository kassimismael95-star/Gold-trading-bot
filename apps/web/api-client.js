/* Shared authenticated API client. Token is kept in session memory, not localStorage. */
let accessToken=null;
export function setAccessToken(token){accessToken=token||null;}
export async function api(path,options={}){
 const headers={...(options.headers||{}),"Content-Type":"application/json"};
 if(accessToken) headers.Authorization=`Bearer ${accessToken}`;
 const response=await fetch(path,{...options,headers});
 const body=await response.json().catch(()=>({}));
 if(!response.ok) throw new Error(body.error||`Request failed (${response.status})`);
 return body;
}
