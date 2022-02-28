from consts import *
from shared_tests import *
from brownie import web3, chain

def test_registerClaim_updateFlipSupply_executeClaim(cf, stakedMin):
    _, amountStaked = stakedMin
    claimAmount = amountStaked
    receiver = cf.DENICE

    registerClaimTest(
        cf,
        JUNK_HEX,
        MIN_STAKE,
        claimAmount,
        receiver,
        chain.time() + (2 * CLAIM_DELAY)
    )

    stateChainBlockNumber = 1

    callDataNoSig = cf.stakeManager.updateFlipSupply.encode_input(agg_null_sig(cf.keyManager.address, chain.id), NEW_TOTAL_SUPPLY_MINT, stateChainBlockNumber)
    tx = cf.stakeManager.updateFlipSupply(AGG_SIGNER_1.getSigData(callDataNoSig, cf.keyManager.address), NEW_TOTAL_SUPPLY_MINT, stateChainBlockNumber, cf.FR_ALICE)


    # Check things that should've changed
    assert cf.flip.balanceOf(cf.stakeManager) == amountStaked + NEW_TOTAL_SUPPLY_MINT - INIT_SUPPLY + STAKEMANAGER_INITIAL_BALANCE
    assert cf.flip.totalSupply() == NEW_TOTAL_SUPPLY_MINT
    assert tx.events["FlipSupplyUpdated"][0].values() == [INIT_SUPPLY, NEW_TOTAL_SUPPLY_MINT, stateChainBlockNumber]

    # Check things that shouldn't have changed
    assert cf.stakeManager.getMinimumStake() == MIN_STAKE

    chain.sleep(CLAIM_DELAY + 5)
    cf.stakeManager.executeClaim(JUNK_HEX)

    # Check things that should've changed
    assert cf.stakeManager.getPendingClaim(JUNK_HEX) == NULL_CLAIM

    assert cf.flip.balanceOf(cf.stakeManager) == amountStaked + (NEW_TOTAL_SUPPLY_MINT - INIT_SUPPLY + STAKEMANAGER_INITIAL_BALANCE) - claimAmount
    assert cf.flip.balanceOf(receiver) == claimAmount
    assert cf.flip.totalSupply() == NEW_TOTAL_SUPPLY_MINT

    # Check things that shouldn't have changed
    assert cf.stakeManager.getMinimumStake() == MIN_STAKE
