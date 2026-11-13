// Operator runs ONLY after normal STOP/cleanup. Loads symbols, never firmware.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const folder=__dirname;
const manifest=JSON.parse(fs.readFileSync(path.join(folder,'BUILD_MANIFEST.json'),'utf8'));
const image=path.join(folder,manifest.master.path);
if(manifest.status!=='passed' || crypto.createHash('sha256').update(fs.readFileSync(image)).digest('hex')!==manifest.master.sha256)
    throw Error('Candidate/image hash mismatch');
const output=path.join(folder,'Results','01-observe','attempt1','master-batch.bin');
if(fs.existsSync(output))throw Error('Preserve the existing export; output already exists');
const ds=initScripting();ds.setScriptingTimeout(15000);let session;
try {
    ds.configure(path.join(folder,'MASTER_TARGET.ccxml'));session=ds.openSession(/cortex/i);
    session.target.connect();session.target.halt();session.symbols.load(image);
    const address=session.symbols.getAddress('gMasterBatchInfo');
    const length=Number(session.expressions.evaluate('sizeof(gMasterBatchInfo)'));
    if(length!==1448 || length!==manifest.diagnostic_size_bytes)throw Error('Unexpected batch layout');
    const words=session.memory.read(address,length/4,32);
    if(words.length!==length/4)throw Error('Incomplete debugger memory read');
    const bytes=Buffer.alloc(length);words.forEach((value,i)=>bytes.writeUInt32LE(Number(value)>>>0,i*4));
    if(bytes.readUInt32LE(0)!==1 || bytes.readUInt32LE(4)!==length ||
       (bytes.readUInt32LE(8)===0 && bytes.readUInt32LE(12)===0))throw Error('No valid acquisition snapshot');
    fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,bytes,{flag:'wx'});
    console.log('Batch diagnostics saved: '+output);
} finally {
    try {if(session)session.target.run(false);} finally {ds.shutdown();}
}
