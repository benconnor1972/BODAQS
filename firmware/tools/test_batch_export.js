// Exercise the exact CCS exporter with stand-ins; no device or filesystem writes.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'export_batch_diagnostics.js'),'utf8');
for(const scenario of ['ok','layout','short','version','scope','read','hash','overwrite','resume']) {
    const calls=[];let saved;
    const bytes=Buffer.alloc(1448);bytes.writeUInt32LE(scenario==='version'?0:1,0);
    bytes.writeUInt32LE(1448,4);bytes.writeUInt32LE(scenario==='scope'?0:123,8);
    const manifest={status:'passed',master:{path:'master.out',sha256:'digest'},diagnostic_size_bytes:1448};
    const mockFs={readFileSync:p=>p.endsWith('BUILD_MANIFEST.json')?JSON.stringify(manifest):Buffer.from('image'),
        existsSync:()=>scenario==='overwrite',mkdirSync:()=>{},writeFileSync:(p,data,options)=>{assert.equal(options.flag,'wx');saved=data;}};
    const session={target:{connect:()=>calls.push('connect'),halt:()=>calls.push('halt'),
        run:()=>{calls.push('run');if(scenario==='resume')throw Error('resume failed');}},
        symbols:{load:()=>calls.push('symbols'),getAddress:()=>0x20210000},
        expressions:{evaluate:()=>scenario==='layout'?1:1448},
        memory:{read:()=>{calls.push('read');if(scenario==='read')throw Error('read failed');
            return Array.from({length:scenario==='short'?361:362},(_,i)=>bytes.readUInt32LE(i*4));}}};
    const ds={setScriptingTimeout:()=>{},configure:()=>{},openSession:()=>session,shutdown:()=>calls.push('shutdown')};
    let error;
    try {vm.runInNewContext(source,{require:name=>name==='fs'?mockFs:name==='crypto'?
        {createHash:()=>({update:()=>({digest:()=>scenario==='hash'?'wrong':'digest'})})}:require(name),
        __dirname:'/fixture',Buffer,initScripting:()=>{calls.push('init');return ds;},console:{log:()=>{}}});}
    catch(e){error=e;}
    assert.equal(!!error,scenario!=='ok',scenario);
    if(['hash','overwrite'].includes(scenario))assert.deepEqual(calls,[]);
    else {assert.deepEqual(calls.slice(0,4),['init','connect','halt','symbols']);assert.deepEqual(calls.slice(-2),['run','shutdown']);}
    assert.equal(!!saved,['ok','resume'].includes(scenario));
    if(saved)assert.deepEqual(saved,bytes);
}
console.log('PASS: exact exporter, layout/identity/read/hash/overwrite failures, resume/shutdown, no flash/reset API');
