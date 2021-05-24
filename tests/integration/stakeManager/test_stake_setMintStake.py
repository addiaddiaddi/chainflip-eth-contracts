from consts import *
from shared_tests import *
from brownie import reverts, web3


def test_setMinStake_stake(cf):
    # Set new minimum stake
    newMinStake = int(MIN_STAKE * 1.5)
    callDataNoSig = cf.stakeManager.setMinStake.encode_input(NULL_SIG_DATA, newMinStake)
    setMinStakeTx = cf.stakeManager.setMinStake(GOV_SIGNER_1.getSigData(callDataNoSig), newMinStake)

    # Check things that should've changed
    assert cf.stakeManager.getMinimumStake() == newMinStake
    assert setMinStakeTx.events["MinStakeChanged"][0].values() == [MIN_STAKE, newMinStake]
    # Check things that shouldn't have changed
    inflation = getInflation(cf.stakeManager.tx.block_number, setMinStakeTx.block_number, EMISSION_PER_BLOCK)
    assert cf.flip.balanceOf(cf.stakeManager) == 0
    assert cf.stakeManager.getInflationInFuture(0) == inflation
    assert cf.stakeManager.getTotalStakeInFuture(0) == inflation
    assert cf.stakeManager.getEmissionPerBlock() == EMISSION_PER_BLOCK
    assert cf.stakeManager.getLastMintBlockNum() == cf.stakeManager.tx.block_number

    # Staking an amount valid for the last min but not the current min should revert
    with reverts(REV_MSG_MIN_STAKE):
        cf.stakeManager.stake(JUNK_INT, MIN_STAKE, cf.FR_ALICE)
    
    stakeTx = cf.stakeManager.stake(JUNK_INT, newMinStake, cf.FR_ALICE)

    stakeTest(
        cf,
        0,
        JUNK_INT,
        cf.stakeManager.tx.block_number,
        EMISSION_PER_BLOCK,
        newMinStake,
        stakeTx,
        newMinStake
    )