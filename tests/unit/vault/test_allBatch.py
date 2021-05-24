from consts import *
from brownie import reverts, web3
from brownie.test import given, strategy
from random import choices


@given(
    fetchAmounts=strategy('uint[]', max_value=TEST_AMNT, max_length=int(INIT_TOKEN_SUPPLY / TEST_AMNT)),
    fetchSwapIDs=strategy('bytes32[]', unique=True),
    tranRecipients=strategy('address[]', unique=True),
    tranAmounts=strategy('uint[]', max_value=TEST_AMNT),
    sender=strategy('address')
)
def test_allBatch(cf, token, token2, DepositToken, DepositEth, fetchAmounts, fetchSwapIDs, tranRecipients, tranAmounts, sender):
    # Sort out deposits first so enough can be sent to the create2 addresses
    fetchMinLen = trimToShortest([fetchAmounts, fetchSwapIDs])
    tokensList = [ETH_ADDR, token, token2]
    fetchTokens = choices(tokensList, k=fetchMinLen)
    ethTotal = 0
    tokenATotal = 0
    tokenBTotal = 0

    fetchTotals = {tok: sum([fetchAmounts[i] for i, x in enumerate(fetchTokens) if x == tok]) for tok in tokensList}

    # Transfer tokens to the deposit addresses
    for am, id, tok in zip(fetchAmounts, fetchSwapIDs, fetchTokens):
        # Get the address to deposit to and deposit
        if tok == ETH_ADDR:
            depositAddr = getCreate2Addr(cf.vault.address, id.hex(), DepositEth, "")
            cf.DEPLOYER.transfer(depositAddr, am)
        else:
            depositAddr = getCreate2Addr(cf.vault.address, id.hex(), DepositToken, cleanHexStrPad(tok.address))
            tok.transfer(depositAddr, am, {'from': cf.DEPLOYER})
    
    assert cf.vault.balance() == 0
    assert token.balanceOf(cf.vault) == 0
    assert token2.balanceOf(cf.vault) == 0

    # Transfers
    tranMinLen = trimToShortest([tranRecipients, tranAmounts])
    tranTokens = choices(tokensList, k=tranMinLen)

    tranTotals = {tok: sum([tranAmounts[i] for i, x in enumerate(tranTokens) if x == tok]) for tok in tokensList}

    ethBals = [web3.eth.getBalance(str(recip)) for recip in tranRecipients]
    tokenBals = [token.balanceOf(recip) for recip in tranRecipients]
    token2Bals = [token2.balanceOf(recip) for recip in tranRecipients]

    callDataNoSig = cf.vault.allBatch.encode_input(NULL_SIG_DATA, fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts)

    # If it tries to transfer an amount of tokens out the vault that is more than it fetched, it'll revert
    if any([tranTotals[tok] > fetchTotals[tok] for tok in tokensList]):
        with reverts():
            cf.vault.allBatch(AGG_SIGNER_1.getSigData(callDataNoSig), fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts, {'from': sender})
    else:
        tx = cf.vault.allBatch(AGG_SIGNER_1.getSigData(callDataNoSig), fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts, {'from': sender})

        assert cf.vault.balance() == fetchTotals[ETH_ADDR] - tranTotals[ETH_ADDR]
        assert token.balanceOf(cf.vault) == fetchTotals[token] - tranTotals[token]
        assert token2.balanceOf(cf.vault) == fetchTotals[token2] - tranTotals[token2]
        
        for i in range(len(tranRecipients)):
            if tranTokens[i] == ETH_ADDR:
                assert web3.eth.getBalance(str(tranRecipients[i])) == ethBals[i] + tranAmounts[i]
            elif tranTokens[i] == token:
                assert token.balanceOf(tranRecipients[i]) == tokenBals[i] + tranAmounts[i]
            elif tranTokens[i] == token2:
                assert token2.balanceOf(tranRecipients[i]) == token2Bals[i] + tranAmounts[i]
            else:
                assert False, "Panic"


@given(
    fetchSwapIDs=strategy('bytes32[]'),
    tranRecipients=strategy('address[]', unique=True),
    tranAmounts=strategy('uint[]', max_value=TEST_AMNT),
    sender=strategy('address'),
    randK=strategy('uint', min_value=1, max_value=100)
)
def test_allBatch_rev_fetch_array_length(cf, token, token2, DepositToken, DepositEth, fetchSwapIDs, tranRecipients, tranAmounts, sender, randK):
    # Make sure the lengths are always different somewhere
    tokensList = [ETH_ADDR, token, token2]
    fetchTokens = choices(tokensList, k=len(fetchSwapIDs) + randK)
    
    tranMinLen = trimToShortest([tranRecipients, tranAmounts])
    tranTokens = choices(tokensList, k=tranMinLen)

    callDataNoSig = cf.vault.allBatch.encode_input(NULL_SIG_DATA, fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts)

    with reverts(REV_MSG_V_ARR_LEN):
        cf.vault.allBatch(AGG_SIGNER_1.getSigData(callDataNoSig), fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts, {'from': sender})


@given(
    fetchSwapIDs=strategy('bytes32[]'),
    tranRecipients=strategy('address[]', unique=True),
    tranAmounts=strategy('uint[]', max_value=TEST_AMNT),
    sender=strategy('address'),
    randK=strategy('uint', min_value=1, max_value=100)
)
def test_allBatch_rev_transfer_array_length(cf, token, token2, DepositToken, DepositEth, fetchSwapIDs, tranRecipients, tranAmounts, sender, randK):
    # Make sure the lengths are always different somewhere
    tokensList = [ETH_ADDR, token, token2]
    fetchTokens = choices(tokensList, k=len(fetchSwapIDs) + randK)
    
    tranMinLen = trimToShortest([tranRecipients, tranAmounts])
    tranTokens = choices(tokensList, k=tranMinLen + randK)

    callDataNoSig = cf.vault.allBatch.encode_input(NULL_SIG_DATA, fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts)

    with reverts(REV_MSG_V_ARR_LEN):
        cf.vault.allBatch(AGG_SIGNER_1.getSigData(callDataNoSig), fetchSwapIDs, fetchTokens, tranTokens, tranRecipients, tranAmounts, {'from': sender})


def test_allBatch_rev_msgHash(cf):
    callDataNoSig = cf.vault.allBatch.encode_input(NULL_SIG_DATA, [JUNK_HEX], [ETH_ADDR], [ETH_ADDR], [cf.ALICE], [TEST_AMNT])
    sigData = AGG_SIGNER_1.getSigData(callDataNoSig)
    sigData[0] += 1

    with reverts(REV_MSG_MSGHASH):
        cf.vault.allBatch(sigData, [JUNK_HEX], [ETH_ADDR], [ETH_ADDR], [cf.ALICE], [TEST_AMNT])


def test_allBatch_rev_sig(cf):
    callDataNoSig = cf.vault.allBatch.encode_input(NULL_SIG_DATA, [JUNK_HEX], [ETH_ADDR], [ETH_ADDR], [cf.ALICE], [TEST_AMNT])
    sigData = AGG_SIGNER_1.getSigData(callDataNoSig)
    sigData[1] += 1

    with reverts(REV_MSG_SIG):
        cf.vault.allBatch(sigData, [JUNK_HEX], [ETH_ADDR], [ETH_ADDR], [cf.ALICE], [TEST_AMNT])