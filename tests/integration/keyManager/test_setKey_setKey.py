from consts import *
from shared_tests import *
from brownie import reverts


def test_setAggKeyWithAggKey_setAggKeyWithAggKey(cf):
    # Change agg keys
    setAggKeyWithAggKey_test(cf)

    # Try to change agg key with old agg key
    callDataNoSig = cf.keyManager.setAggKeyWithAggKey.encode_input(NULL_SIG_DATA, GOV_SIGNER_1.getPubData())
    with reverts(REV_MSG_SIG):
        cf.keyManager.setAggKeyWithAggKey(AGG_SIGNER_1.getSigData(callDataNoSig), GOV_SIGNER_1.getPubData())

    # Try to change agg key with gov key
    with reverts(REV_MSG_SIG):
        cf.keyManager.setAggKeyWithAggKey(GOV_SIGNER_1.getSigData(callDataNoSig), GOV_SIGNER_1.getPubData())
    
    # Change agg key to gov key since there's no AGG_SIGNER_3
    tx = cf.keyManager.setAggKeyWithAggKey(AGG_SIGNER_2.getSigData(callDataNoSig), GOV_SIGNER_1.getPubData())

    assert cf.keyManager.getAggregateKey() == GOV_SIGNER_1.getPubDataWith0x()
    assert tx.events["KeyChange"][0].values() == [True, AGG_SIGNER_2.getPubDataWith0x(), GOV_SIGNER_1.getPubDataWith0x()]
    assert cf.keyManager.getGovernanceKey() == GOV_SIGNER_1.getPubDataWith0x()
    txTimeTest(cf.keyManager.getLastValidateTime(), tx)


def test_setGovKeyWithGovKey_setAggKeyWithGovKey(cf):
    # Change the gov key
    setGovKeyWithGovKey_test(cf)

    # Try to change agg key with old gov key
    callDataNoSig = cf.keyManager.setAggKeyWithGovKey.encode_input(NULL_SIG_DATA, AGG_SIGNER_2.getPubData())
    with reverts(REV_MSG_SIG):
        cf.keyManager.setAggKeyWithGovKey(GOV_SIGNER_1.getSigData(callDataNoSig), AGG_SIGNER_2.getPubData())
    
    # Change agg key with gov key
    tx = cf.keyManager.setAggKeyWithGovKey(GOV_SIGNER_2.getSigData(callDataNoSig), AGG_SIGNER_2.getPubData())

    assert cf.keyManager.getAggregateKey() == AGG_SIGNER_2.getPubDataWith0x()
    assert tx.events["KeyChange"][0].values() == [False, AGG_SIGNER_1.getPubDataWith0x(), AGG_SIGNER_2.getPubDataWith0x()]
    assert cf.keyManager.getGovernanceKey() == GOV_SIGNER_2.getPubDataWith0x()
    txTimeTest(cf.keyManager.getLastValidateTime(), tx)

