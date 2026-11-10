// Node VM uses the exact exporter body with read-only debugger stand-ins.
const fs=require("fs"),vm=require("vm"),assert=require("assert");
const source=fs.readFileSync(require("path").join(__dirname,"export_spi_trace.js"),"utf8");
for(const scenario of ["ok","unfrozen","short","resume","read","hash","overwrite"]) {
    const calls=[];let saved;
    const trace=Buffer.alloc(7328);trace.writeUInt32LE(1,0);trace.writeUInt32LE(7328,4);
    trace.writeUInt32LE(scenario==="unfrozen"?0:1,24);
    const manifest={status:"passed",variants:{trace:{master:{path:"master.out",sha256:"image-digest"}}}};
    const mockFs={readFileSync:p=>p.endsWith("BUILD_MANIFEST.json")?JSON.stringify(manifest):Buffer.from("image"),
        existsSync:()=>scenario==="overwrite",mkdirSync:()=>{},writeFileSync:(p,data)=>{saved=data;}};
    const session={target:{connect:()=>calls.push("connect"),halt:()=>calls.push("halt"),
        run:wait=>{assert.strictEqual(wait,false);calls.push("run");if(scenario==="resume")throw Error("resume failed");}},
        symbols:{load:p=>calls.push("symbols"),getAddress:name=>{assert.strictEqual(name,"gMasterSpiTrace");return 0x20210000;}},
        expressions:{evaluate:()=>7328},memory:{read:(address,count,bits)=>{
            calls.push("read");assert.strictEqual(address,0x20210000);assert.strictEqual(bits,32);
            if(scenario==="read")throw Error("read failed");
            return Array.from({length:scenario==="short"?count-1:count},(_,i)=>trace.readUInt32LE(i*4));}}};
    const ds={setScriptingTimeout:()=>{},configure:()=>{},openSession:()=>session,shutdown:()=>calls.push("shutdown")};
    let error;
    try {vm.runInNewContext(source,{require:name=>name==="fs"?mockFs:name==="crypto"?
        {createHash:()=>({update:()=>({digest:()=>scenario==="hash"?"wrong":"image-digest"})})}:require(name),
        __dirname:"/fixture",Buffer,initScripting:()=>{calls.push("init");return ds;},console:{log:()=>{}}});}
    catch(e) {error=e;}
    assert.strictEqual(!!error,scenario!=="ok",scenario);
    if(["hash","overwrite"].includes(scenario))assert.deepStrictEqual(calls,[]);
    else {
        assert.deepStrictEqual(calls,["init","connect","halt","symbols","read","run","shutdown"]);
        assert.strictEqual(!!saved,["ok","resume"].includes(scenario));
    }
    if(saved)assert.deepStrictEqual(saved,trace);
}
console.log("read-only exporter: exact layout, no flash/reset APIs, short/error/overwrite refusal and visible resume failure PASS");
