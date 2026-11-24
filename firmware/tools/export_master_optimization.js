// Read-only addition to the existing, operator-selected CCS snapshot export.
// Never connects, halts, resets, resumes or loads firmware.
function exportBodaqsOptimization(session, operatorConfirmedStopped) {
    if (operatorConfirmedStopped !== true) throw 'Confirm recording and cleanup stopped';
    var result = [];
    for (var i = 0; i < 3; ++i)
        result.push(Number(session.expression.evaluate('gMasterOptimizationInfo[' + i + ']')));
    if (result[0] !== 1 || (result[1] !== 0 && result[1] !== 1) ||
        (result[2] !== 0 && result[2] !== 1)) throw 'Unexpected optimization marker';
    return JSON.stringify({schema:'bodaqs.master-optimization.v1',
        optimization:result, meaning:['version','block_crc','can_first']}, null, 2);
}
