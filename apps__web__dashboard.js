import {listAccounts} from './accounts.js';
export async function refreshAccountPanel(render){try{render(await listAccounts());}catch(error){render({error:error.message});}}
