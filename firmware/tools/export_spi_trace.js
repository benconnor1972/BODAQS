// Run ONLY after normal STOP/file closure with CCS scripting/run.bat.
// Reads the frozen diagnostic block; symbols.load does not program the target.
const fs=require("fs"),path=require("path"),crypto=require("crypto");
const folder=__dirname;
const manifest=JSON.parse(fs.readFileSync(path.join(folder,"BUILD_MANIFEST.json"),"utf8"));
const variant=manifest.variants.trace;
const image=path.join(folder,variant.master.path);
const digest=crypto.createHash("sha256").update(fs.readFileSync(image)).digest("hex");
if(manifest.status!=="passed" || digest!==variant.master.sha256)throw Error("Candidate/image hash mismatch");
const output=path.join(folder,"Evidence","master-trace.bin");
if(fs.existsSync(output))throw Error("Preserve the existing export before another capture");
const ds=initScripting();ds.setScriptingTimeout(15000);let session;
try {
    ds.configure(path.join(folder,"MASTER_TARGET.ccxml"));session=ds.openSession(/cortex/i);
    session.target.connect();session.target.halt();session.symbols.load(image);
    const address=session.symbols.getAddress("gMasterSpiTrace");
    const length=Number(session.expressions.evaluate("sizeof(gMasterSpiTrace)"));
    if(length!==7328)throw Error("Unexpected trace layout");
    const words=session.memory.read(address,length/4,32);
    if(words.length!==length/4)throw Error("Incomplete debugger memory read");
    const bytes=Buffer.alloc(length);words.forEach((value,i)=>bytes.writeUInt32LE(Number(value),i*4));
    if(bytes.readUInt32LE(0)!==1 || bytes.readUInt32LE(4)!==length || bytes.readUInt32LE(24)!==1 || bytes.readUInt32LE(28)!==0)
        throw Error("Trace is unfrozen, saturated or incompatible; no export written");
    fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,bytes);
    console.log("Frozen trace saved: "+output);
} finally {
    try {
        if(session)session.target.run(false);
    } finally { ds.shutdown(); }
}
