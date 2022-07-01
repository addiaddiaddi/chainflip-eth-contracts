import sys
from os import path
import traceback

sys.path.append(path.abspath("scripts"))
import Tick
import TickMath
import SwapMath
import FixedPoint128
import LiquidityMath
import Position
import SqrtPriceMath
import SafeMath
from Account import Account
from dataclasses import dataclass


@dataclass
class Slot0:
    ## the current price
    sqrtPriceX96: int
    ## the current tick
    tick: int
    ## the current protocol fee as a percentage of the swap fee taken on withdrawal
    ## represented as an integer denominator (1#x)%
    feeProtocol: int


@dataclass
class ModifyPositionParams:
    ## the address that owns the position
    owner: int
    ## the lower and upper tick of the position
    tickLower: int
    tickUpper: int
    ## any change in liquidity
    liquidityDelta: int


@dataclass
class SwapCache:
    ## the protocol fee for the input token
    feeProtocol: int
    ## liquidity at the beginning of the swap
    liquidityStart: int


## the top level state of the swap, the results of which are recorded in storage at the end
@dataclass
class SwapState:
    ## the amount remaining to be swapped in#out of the input#output asset
    amountSpecifiedRemaining: int
    ## the amount already swapped out#in of the output#input asset
    amountCalculated: int
    ## current sqrt(price)
    sqrtPriceX96: int
    ## the tick associated with the current price
    tick: int
    ## the global fee growth of the input token
    feeGrowthGlobalX128: int
    ## amount of input token paid as protocol fee
    protocolFee: int
    ## the current liquidity in range
    liquidity: int


@dataclass
class StepComputations:
    ## the price at the beginning of the step
    sqrtPriceStartX96: int
    ## the next tick to swap to from the current tick in the swap direction
    tickNext: int
    ## whether tickNext is initialized or not
    initialized: bool
    ## sqrt(price) for the next tick (1#0)
    sqrtPriceNextX96: int
    ## how much is being swapped in in this step
    amountIn: int
    ## how much is being swapped out
    amountOut: int
    ## how much fee is being paid in
    feeAmount: int


class UniswapPool(Account):

    # Class variables
    fee = None
    tickSpacing = None
    maxLiquidityPerTick = None
    slot0 = Slot0(0, 0, 0)
    feeGrowthGlobal0X128 = None
    feeGrowthGlobal1X128 = None
    protocolFees = None
    liquidity = None
    ticks = None
    tickBitmap = dict()
    positions = None

    # Constructor
    def __init__(self, fee, tickSpacing):
        # TODO: Initialize pool balances here or in initialize function call
        super().__init__("UniswapPool", 0, 0)
        self.fee = fee
        self.tickSpacing = tickSpacing
        self.maxLiquidityPerTick = Tick.tickSpacingToMaxLiquidityPerTick(tickSpacing)

    ### @dev Common checks for valid tick inputs.
    @classmethod
    def checkTicks(tickLower, tickUpper):
        assert tickLower < tickUpper, "TLU"
        assert tickLower >= TickMath.MIN_TICK, "TLM"
        assert tickUpper <= TickMath.MAX_TICK, "TUM"

    ## Skipped `snapshotCumulativesInside`

    ### @inheritdoc IUniswapV3PoolActions
    ### @dev not locked because it initializes unlocked
    def initialize(self, sqrtPriceX96):
        assert self.slot0.sqrtPriceX96 == 0, "AI"

        tick = TickMath.getTickAtSqrtRatio(sqrtPriceX96)

        self.slot0 = Slot0(
            sqrtPriceX96,
            tick,
            0,
        )

    ## @dev Effect some changes to a position
    ## @param params the position details and the change to the position's liquidity to effect
    ## @return position a storage pointer referencing the position with the given owner and tick range
    ## @return amount0 the amount of token0 owed to the pool, negative if the pool should pay the recipient
    ## @return amount1 the amount of token1 owed to the pool, negative if the pool should pay the recipient
    def _modifyPosition(self, params):
        UniswapPool.checkTicks(params.tickLower, params.tickUpper)

        _slot0 = self.slot0
        ## SLOAD for gas optimization

        position = self._updatePosition(
            params.owner, params.tickLower, params.tickUpper, params.liquidityDelta, _slot0.tick
        )

        if params.liquidityDelta != 0:
            if _slot0.tick < params.tickLower:
                ## current tick is below the passed range; liquidity can only become in range by crossing from left to
                ## right, when we'll need _more_ token0 (it's becoming more valuable) so user must provide it
                amount0 = SqrtPriceMath.getAmount0Delta(
                    TickMath.getSqrtRatioAtTick(params.tickLower),
                    TickMath.getSqrtRatioAtTick(params.tickUpper),
                    params.liquidityDelta,
                )
            elif _slot0.tick < params.tickUpper:
                ## current tick is inside the passed range
                liquidityBefore = liquidity
                ## SLOAD for gas optimization

                amount0 = SqrtPriceMath.getAmount0Delta(
                    _slot0.sqrtPriceX96, TickMath.getSqrtRatioAtTick(params.tickUpper), params.liquidityDelta
                )
                amount1 = SqrtPriceMath.getAmount1Delta(
                    TickMath.getSqrtRatioAtTick(params.tickLower), _slot0.sqrtPriceX96, params.liquidityDelta
                )

                liquidity = LiquidityMath.addDelta(liquidityBefore, params.liquidityDelta)
            else:
                ## current tick is above the passed range; liquidity can only become in range by crossing from right to
                ## left, when we'll need _more_ token1 (it's becoming more valuable) so user must provide it
                amount1 = SqrtPriceMath.getAmount1Delta(
                    TickMath.getSqrtRatioAtTick(params.tickLower),
                    TickMath.getSqrtRatioAtTick(params.tickUpper),
                    params.liquidityDelta,
                )

        return (position, amount0, amount1)

    ### @dev Gets and updates a position with the given liquidity delta
    ### @param owner the owner of the position
    ### @param tickLower the lower tick of the position's tick range
    ### @param tickUpper the upper tick of the position's tick range
    ### @param tick the current tick, passed to avoid sloads
    def _updatePosition(self, owner, tickLower, tickUpper, liquidityDelta, tick):
        # This will create a position if it doesn't exist
        position = Position.get(self.positions, owner, tickLower, tickUpper)

        _feeGrowthGlobal0X128 = self.feeGrowthGlobal0X128
        ## SLOAD for gas optimization
        _feeGrowthGlobal1X128 = self.feeGrowthGlobal1X128
        ## SLOAD for gas optimization

        ## if we need to update the ticks, do it
        if liquidityDelta != 0:
            flippedLower = Tick.update(
                self.ticks,
                tickLower,
                tick,
                liquidityDelta,
                _feeGrowthGlobal0X128,
                _feeGrowthGlobal1X128,
                False,
                self.maxLiquidityPerTick,
            )
            flippedUpper = Tick.update(
                self.ticks,
                tickUpper,
                tick,
                liquidityDelta,
                _feeGrowthGlobal0X128,
                _feeGrowthGlobal1X128,
                True,
                self.maxLiquidityPerTick,
            )

        (feeGrowthInside0X128, feeGrowthInside1X128) = Tick.getFeeGrowthInside(
            self.ticks, tickLower, tickUpper, tick, _feeGrowthGlobal0X128, _feeGrowthGlobal1X128
        )

        position.update(liquidityDelta, feeGrowthInside0X128, feeGrowthInside1X128)

        ## clear any tick data that is no longer needed
        if liquidityDelta < 0:
            if flippedLower:
                Tick.clear(self.ticks, tickLower)
            if flippedUpper:
                Tick.clear(self.ticks, tickUpper)
        return position

    ### @inheritdoc IUniswapV3PoolActions
    ### @dev noDelegateCall is applied indirectly via _modifyPosition
    def mint(self, recipient, tickLower, tickUpper, amount, data):
        assert amount > 0
        (_, amount0Int, amount1Int) = self._modifyPosition(
            ModifyPositionParams(recipient, tickLower, tickUpper, amount)
        )

        amount0 = amount0Int
        amount1 = amount1Int

        if amount0 > 0:
            balance0Before = self.balanceToken0
        if amount1 > 0:
            balance1Before = self.balanceToken1

        # Transfer tokens
        recipient.transferTokens(self, amount0, amount1)

        if amount0 > 0:
            assert SafeMath.add(balance0Before,amount0) <= self.balanceToken0, "M0"
        if amount1 > 0:
            assert SafeMath.add(balance1Before,amount1) <= self.balanceToken1, "M1"

        return (amount0, amount1)

    ### @inheritdoc IUniswapV3PoolActions
    def collect(self, recipient, tickLower, tickUpper, amount0Requested, amount1Requested):
        ## we don't need to checkTicks here, because invalid positions will never have non-zero tokensOwed{0,1}
        ## Hardcoded recipient == msg.sender. If position doesn't exist abort.
        position = Position.get(self.positions, recipient, tickLower, tickUpper)

        # Added this check to prevent creating a new position if the position doesn't exist
        assert position != Position.PositionInfo(0, 0, 0, 0, 0), "Position doesn't exist"

        amount0 = position.tokensOwed0 if (amount0Requested > position.tokensOwed0) else amount0Requested
        amount1 = position.tokensOwed1 if (amount1Requested > position.tokensOwed1) else amount1Requested

        if amount0 > 0:
            position.tokensOwed0 -= amount0
            self.transferTokens(recipient, amount0, 0)
        if amount1 > 0:
            position.tokensOwed1 -= amount1
            self.transferTokens(recipient, 0, amount1)

        return (amount0, amount1)

    ### @inheritdoc IUniswapV3PoolActions
    ### @dev noDelegateCall is applied indirectly via _modifyPosition
    def burn(self, recipient, tickLower, tickUpper, amount):
        assert amount > 0, "Amount must be greater than 0 - prevent creating a new position"

        # Added extra recipient input variable to mimic msg.sender
        (position, amount0Int, amount1Int) = self._modifyPosition(
            ModifyPositionParams(recipient, tickLower, tickUpper, -amount)
        )

        amount0 = -amount0Int
        amount1 = -amount1Int

        if amount0 > 0 or amount1 > 0:
            (position.tokensOwed0, position.tokensOwed1) = (
                position.tokensOwed0 + amount0,
                position.tokensOwed1 + amount1,
            )

        return (amount0, amount1)

    ### @inheritdoc IUniswapV3PoolActions
    def swap(self, recipient, zeroForOne, amountSpecified, sqrtPriceLimitX96, data):
        assert amountSpecified != 0, "AS"

        slot0Start = self.slot0

        if zeroForOne:
            assert (
                sqrtPriceLimitX96 < slot0Start.sqrtPriceX96 and sqrtPriceLimitX96 > TickMath.MIN_SQRT_RATIO
            ), "SPL"
        else:
            assert (
                sqrtPriceLimitX96 > slot0Start.sqrtPriceX96 and sqrtPriceLimitX96 < TickMath.MAX_SQRT_RATIO
            ), "SPL"

        feeProtocol = (slot0Start.feeProtocol % 16) if zeroForOne else (slot0Start.feeProtocol >> 4)

        cache = SwapCache(self.liquidity, feeProtocol, 0, 0, False)

        exactInput = amountSpecified > 0

        feeGrowthGlobalX128 = self.feeGrowthGlobal0X128 if zeroForOne else self.feeGrowthGlobal1X128

        state = SwapState(
            amountSpecified,
            0,
            slot0Start.sqrtPriceX96,
            slot0Start.tick,
            feeGrowthGlobalX128,
            0,
            cache.liquidityStart,
        )

        while state.amountSpecifiedRemaining != 0 and state.sqrtPriceX96 != sqrtPriceLimitX96:
            step = StepComputations()

            step.sqrtPriceStartX96 = state.sqrtPriceX96

            # TODO: Will we need to check the returned initialized state in case we are in the TICK MIN or TICK MAX?
            (step.tickNext, step.initialized) = self.nextTick(state.tick, zeroForOne)

            ## get the price for the next tick
            step.sqrtPriceNextX96 = TickMath.getSqrtRatioAtTick(step.tickNext)

            ## compute values to swap to the target tick, price limit, or point where input#output amount is exhausted
            if zeroForOne:
                sqrtRatioTargetX96 = (
                    sqrtPriceLimitX96 if step.sqrtPriceNextX96 < sqrtPriceLimitX96 else step.sqrtPriceNextX96
                )
            else:
                sqrtRatioTargetX96 = (
                    sqrtPriceLimitX96 if step.sqrtPriceNextX96 > sqrtPriceLimitX96 else step.sqrtPriceNextX96
                )

            (state.sqrtPriceX96, step.amountIn, step.amountOut, step.feeAmount,) = SwapMath.computeSwapStep(
                state.sqrtPriceX96,
                sqrtRatioTargetX96,
                state.liquidity,
                state.amountSpecifiedRemaining,
                self.fee,
            )

            if exactInput:
                state.amountSpecifiedRemaining -= step.amountIn + step.feeAmount
                state.amountCalculated = SafeMath.subInts(state.amountCalculated, step.amountOut)
            else:
                state.amountSpecifiedRemaining += step.amountOut
                state.amountCalculated = SafeMath.addInts(state.amountCalculated, step.amountIn + step.feeAmount)

            ## if the protocol fee is on, calculate how much is owed, decrement feeAmount, and increment protocolFee
            if cache.feeProtocol > 0:
                delta = step.feeAmount  # cache.feeProtocol
                step.feeAmount -= delta
                state.protocolFee += delta

            ## update global fee tracker
            if state.liquidity > 0:
                state.feeGrowthGlobalX128 += step.feeAmount * FixedPoint128.Q128  # state.liquidity

            ## shift tick if we reached the next price
            if state.sqrtPriceX96 == step.sqrtPriceNextX96:
                ## if the tick is initialized, run the tick transition
                if step.initialized:
                    liquidityNet = Tick.cross(
                        self.ticks,
                        step.tickNext,
                        state.feeGrowthGlobalX128 if zeroForOne else self.feeGrowthGlobal0X128,
                        self.feeGrowthGlobal1X128 if zeroForOne else state.feeGrowthGlobalX128,
                    )
                    ## if we're moving leftward, we interpret liquidityNet as the opposite sign
                    ## safe because liquidityNet cannot be type(int128).min
                    if zeroForOne:
                        liquidityNet = -liquidityNet

                    state.liquidity = LiquidityMath.addDelta(state.liquidity, liquidityNet)

                state.tick = (step.tickNext - 1) if zeroForOne else step.tickNext
            elif state.sqrtPriceX96 != step.sqrtPriceStartX96:
                ## recompute unless we're on a lower tick boundary (i.e. already transitioned ticks), and haven't moved
                state.tick = TickMath.getTickAtSqrtRatio(state.sqrtPriceX96)

        ## End of swap loop
        ## update tick and write an oracle entry if the tick change
        if state.tick != slot0Start.tick:
            (self.slot0.sqrtPriceX96, self.slot0.tick) = (
                state.sqrtPriceX96,
                state.tick,
            )
        else:
            ## otherwise just update the price
            self.slot0.sqrtPriceX96 = state.sqrtPriceX96

        ## update liquidity if it changed
        if cache.liquidityStart != state.liquidity:
            self.liquidity = state.liquidity

        ## update fee growth global and, if necessary, protocol fees
        ## overflow is acceptable, protocol has to withdraw before it hits type(uint128).max fees
        if zeroForOne:
            self.feeGrowthGlobal0X128 = state.feeGrowthGlobalX128
            if state.protocolFee > 0:
                self.protocolFees.token0 += state.protocolFee
        else:
            self.feeGrowthGlobal1X128 = state.feeGrowthGlobalX128
            if state.protocolFee > 0:
                self.protocolFees.token1 += state.protocolFee

        (amount0, amount1) = (
            (amountSpecified - state.amountSpecifiedRemaining, state.amountCalculated)
            if (zeroForOne == exactInput)
            else (
                state.amountCalculated,
                amountSpecified - state.amountSpecifiedRemaining,
            )
        )

        ## do the transfers and collect payment
        assert isinstance(recipient, Account)
        if zeroForOne:
            if amount1 < 0:
                self.transferTokens(recipient, 0, -amount1)

            recipient.transferTokens(self, amount0, 0)
        else:
            if amount0 < 0:
                self.transferTokens(recipient, -amount0, 0)

            recipient.transferTokens(self, amount1, 0)

    # It is assumed that the keys are within [MIN_TICK , MAX_TICK]
    # We don't run the risk of overshooting tickNext (out of boundaries) as long as ticks (keys) have been initialized
    # within the boundaries. However, if there is no initialized tick to the left or right we will return the next boundary
    # Then we need to return the initialized bool to indicate that we are at the boundary and it is not an initalized tick.
    # TODO: Check if this is the correct direction for MAX Tick and MIN Tick
    def nextTick(self, tick, zeroForOne):
        sortedKeyList = sorted(list(self.tickBitmap.keys()))
        indexCurrentTick = sortedKeyList.index(tick)
        if zeroForOne:
            if indexCurrentTick == len(sortedKeyList) - 1:
                # No tick to the right
                return TickMath.MAX_TICK, False
            nextTick = sortedKeyList[indexCurrentTick + 1]
        else:
            if indexCurrentTick == 0:
                # No tick to the left
                return TickMath.MIN_TICK, False
            nextTick = sortedKeyList[indexCurrentTick - 1]
        return nextTick, True


def main():
    print("Running")

    pool0 = UniswapPool(1, 2)
    pool1 = UniswapPool(2, 3)

    #TestTokenTransfer(pool0, pool1)

    # print(pool.fee)
    # r = 1
    # msb = 2
    # print(r, msb)
    # (r, msb) = TickMath.add_bit_to_log_2(r, msb, 1, 2)
    # print(r, msb)



# test_fromInput_SqrtPriceMath():
def test_fromInput_fails_price_zero():
    print('fails if price is zero')
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromInput, '',0, 0, expandTo18Decimals(1)/10, False)

def test_fromInput_fails_liquidity_zero(): 
    print('fails if liquidity is zero')
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromInput, '',1, 0, expandTo18Decimals(1)/10, True)
    
def test_fromInput_fails_input_overflow():
    print ('fails if input amount overflows the price')
    price = 2 ** 160 -1
    liquidity = 1024
    amountIn = 1024
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromInput, "Overflow when casting to UINT160" ,price, liquidity, amountIn, False)
    
def test_fromInput_any_input_overflow():
    print('any input amount cannot underflow the price')
    price = 1
    liquidity = 1
    amountIn = 2**255
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromInput, '',price, liquidity, amountIn, False)

def test_fromInput_zeroAmount_zeroForOne():
    print('returns input price if amount in is zero and zeroForOne = true')
    price = 2**96
    assert price == SqrtPriceMath.getNextSqrtPriceFromInput(price, expandTo18Decimals(1)/10, 0, True)

    print('returns input price if amount in is zero and zeroForOne = false')
    price = 2**96
    assert price == SqrtPriceMath.getNextSqrtPriceFromInput(price, expandTo18Decimals(1)/10, 0, False)

def test_fromInput_zeroAmount_notZeroForOne():
    print('returns the minimum price for max inputs')
    sqrtP = 2**160 - 1
    liquidity = TickMath.MAX_UINT128
    print ((liquidity << 96) / sqrtP)
    maxAmountNoOverflow = TickMath.MAX_UINT256 - ((liquidity << 96) / sqrtP)
    assert 1 == SqrtPriceMath.getNextSqrtPriceFromInput(sqrtP, liquidity, maxAmountNoOverflow, True)

def test_fromInput_inputAmount_token1():
    print('input amount of 0.1 token1')
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromInput(
        encodePriceSqrt(1,1),
        expandTo18Decimals(1),
        int(expandTo18Decimals(1)/10),
        False
      )
    assert sqrtQ - 87150978765690771352898345369 == 0

def test_fromInput_inputAmount_token0():
    print('input amount of 0.1 token0')
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromInput(
        encodePriceSqrt(1,1),
        expandTo18Decimals(1),
        int(expandTo18Decimals(1)/10),
        True
      )
    assert sqrtQ - 72025602285694852357767227579 == 0

def test_fromInput_amountInMaxUint96_zeroForOne():
    print('amountIn > type(uint96).max and zeroForOne = true')
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromInput(
        encodePriceSqrt(1,1),
        expandTo18Decimals(10),
        2**100,
        True
      )
    assert sqrtQ - 624999999995069620 == 0

def test_fromInput_amountInMaxUint96_notZeroForOne():
    print('can return 1 with enough amountIn and zeroForOne = true')
    print(encodePriceSqrt(1,1))
    print(int(TickMath.MAX_UINT256 / 2))
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromInput(
        encodePriceSqrt(1,1),
        1,
        int(TickMath.MAX_UINT256 / 2),
        True
      )
    assert sqrtQ - 1 == 0

# Test getNextSqrtPriceFromOutput
def test_fromOutput_fails_zeroPrice():
    print('fails if price is zero')
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',0, 0, expandTo18Decimals(1)/10, False)

def test_fromOutput_fails_liquidityZero():
    print('fails if price is zero')
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',1, 0, expandTo18Decimals(1)/10, True)

def test_fromOutput_fails_equalOutputReserves_token0():
    print("fails if output amount is exactly the virtual reserves of token0")
    price = 20282409603651670423947251286016
    liquidity = 1024
    amountOut = 4
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',price, liquidity, amountOut, False)

def test_fromOutput_fails_greaterOutputReserves_token0():
    print("fails if output amount is greater than virtual reserves of token0")
    price = 20282409603651670423947251286016
    liquidity = 1024
    amountOut = 5
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',price, liquidity, amountOut, False)

def test_fromOutput_fails_greaterOutputReserves_token1():
    print("fails if output amount is greater than virtual reserves of token1")
    price = 20282409603651670423947251286016
    liquidity = 1024
    amountOut = 262145
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',price, liquidity, amountOut, True)

def test_fromOutput_fails_equalOutputReserves_token1():
    print("fails if output amount is exactly the virtual reserves of token1")
    price = 20282409603651670423947251286016
    liquidity = 1024
    amountOut = 262144
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',price, liquidity, amountOut, True)

def test_fromOutput_output_lessThanReserves_token1():
    print('succeeds if output amount is just less than the virtual reserves of token1')
    price = 20282409603651670423947251286016
    liquidity = 1024
    amountOut = 262143    
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromOutput(price, liquidity, amountOut, True)
    assert sqrtQ - 77371252455336267181195264 == 0

def test_fromOutput_puzzlingEchidnaTest():
    print ('puzzling echidna test')
    price = 20282409603651670423947251286016
    liquidity = 1024
    amountOut = 4    
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',price, liquidity, amountOut, False)

def test_fromOutput_zeroAmountIn_zeroForOne():
    print('returns input price if amount in is zero and zeroForOne = true')
    price = encodePriceSqrt(1,1)
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromOutput(price, int(expandTo18Decimals(1)/10), 0, True)
    assert sqrtQ - price == 0

def test_fromOutput_zeroAmountIn_notZeroForOne():
    print('returns input price if amount in is zero and zeroForOne = false')
    price = encodePriceSqrt(1,1)
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromOutput(price, int(expandTo18Decimals(1)/10), 0, False)
    assert sqrtQ - price == 0

def test_fromOutput_outputAmount_token1_notZeroForOne():
    print('output amount of 0.1 token1')
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromOutput(encodePriceSqrt(1,1), expandTo18Decimals(1), int(expandTo18Decimals(1)/10), False)
    assert sqrtQ - 88031291682515930659493278152 == 0

def test_fromOutput_outputAmount_token1_zeroForOne():
    print('output amount of 0.1 token1')
    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromOutput(encodePriceSqrt(1,1), expandTo18Decimals(1), int(expandTo18Decimals(1)/10), True)
    assert sqrtQ - 71305346262837903834189555302 == 0

def test_fails_impossibleAmountOut_zeroForOne():
    print('reverts if amountOut is impossible in zero for one direction')
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',encodePriceSqrt(1, 1), 1, int(TickMath.MAX_UINT256 / 2), True)

def test_fails_impossibleAmountOut_notZeroForOne():
    print('reverts if amountOut is impossible in zero for one direction')
    tryExceptHandler(SqrtPriceMath.getNextSqrtPriceFromOutput, '',encodePriceSqrt(1, 1), 1, int(TickMath.MAX_UINT256 / 2), False)


# getAmount0Delta

def test_getAmount0Delta_zeroLiquidity():
    print('returns if liquidity is zero')
    sqrtQ = SqrtPriceMath.getAmount0Delta(encodePriceSqrt(1,1), encodePriceSqrt(2,1), 0, True)
    assert sqrtQ == 0

def test_getAmount0Delta_equalPrices():
    print('returns 0 if prices are equal')
    sqrtQ = SqrtPriceMath.getAmount0Delta(encodePriceSqrt(1,1), encodePriceSqrt(1,1), 0, True)
    assert sqrtQ == 0

def test_getAmount0Delta_returnsAmount1():
    print('returns 0.1 amount1 for price of 1 to 1.21')
    print(encodePriceSqrt(1,1))
    print(encodePriceSqrt(121,100))
    print(121*2**96 / 100)
    amount0 = SqrtPriceMath.getAmount0Delta(encodePriceSqrt(1,1), encodePriceSqrt(121,100), expandTo18Decimals(1), True)
    assert amount0 - 90909090909090910 == 0

    
    # amount0RoundedDown = SqrtPriceMath.getAmount0Delta(encodePriceSqrt(1,1), encodePriceSqrt(121,100), expandTo18Decimals(1), False)
    # assert amount0RoundedDown - (amount0-1) == 0


def test_getAmount0Delta_priceOverflow():
    print('works for prices that overflow')

    amount0Up = SqrtPriceMath.getAmount0Delta(2**90,2**96, expandTo18Decimals(1), True)
    amount0Down = SqrtPriceMath.getAmount0Delta(2**90,2**96, expandTo18Decimals(1), False)
    assert amount0Up - (amount0Down+1) == 0

# getAmount1Delta

def test_getAmount1Delta_zeroLiquidity():
    print('returns if liquidity is zero')
    sqrtQ = SqrtPriceMath.getAmount1Delta(encodePriceSqrt(1,1), encodePriceSqrt(2,1), 0, True)
    assert sqrtQ == 0

def test_getAmount1Delta_equalPrices():
    print('returns 0 if prices are equal')
    sqrtQ = SqrtPriceMath.getAmount1Delta(encodePriceSqrt(1,1), encodePriceSqrt(1,1), 0, True)
    assert sqrtQ == 0

def test_getAmount1Delta_returnsAmount1():
    print('returns 0.1 amount1 for price of 1 to 1.21')
    amount0 = SqrtPriceMath.getAmount1Delta(encodePriceSqrt(1,1), encodePriceSqrt(121,100), expandTo18Decimals(1), True)
    assert amount0 - 100000000000000000 == 0

    amount1RoundedDown = SqrtPriceMath.getAmount1Delta(encodePriceSqrt(1,1), encodePriceSqrt(121,100), expandTo18Decimals(1), False)
    assert amount1RoundedDown - (amount0-1) == 0    

# Swap Computation
def test_swap():
    print("swap computation")
    ## getNextSqrtPriceInvariants(1025574284609383690408304870162715216695788925244,50015962439936049619261659728067971248,406,true)
    sqrtP = 1025574284609383690408304870162715216695788925244
    liquidity = 50015962439936049619261659728067971248
    zeroForOne = True
    amountIn = 406

    sqrtQ = SqrtPriceMath.getNextSqrtPriceFromInput(sqrtP, liquidity, amountIn, zeroForOne)
    assert sqrtQ - 1025574284609383582644711336373707553698163132913 == 0

    amount0Delta = SqrtPriceMath.getAmount0Delta(sqrtQ, sqrtP, liquidity, True)
    assert amount0Delta - 406 == 0



def encodePriceSqrt(reserve1, reserve0):
    # Making the division by reserve0 converts it into a float which causes python to lose precision
    return int(reserve1 * 2**96 / reserve0)


def expandTo18Decimals(number):
    # Converting to int because python cannot shl on a float
    return int(number * 10 ** 18)

def TestTokenTransfer(account0, account1):
    # Token Transfer Test
    account0.balanceToken0 = 100
    account0.balanceToken1 = 100
    account1.balanceToken0 = 100
    account1.balanceToken1 = 100

    account0.transferTokens(account1, 25, 25)

    assert account0.balanceToken0 == 75
    assert account0.balanceToken1 == 75
    assert account1.balanceToken0 == 125
    assert account1.balanceToken1 == 125

    tryExceptHandler(account0.transferTokens, "Negative amount",-25, 25)
    tryExceptHandler(account0.transferTokens, "Insufficient balance", 150, 25)


def tryExceptHandler(fcn, assertMessage,*args):
    reverted = False
    try:
        fcn(*args)
    except AssertionError as msg:
        reverted = True
        _, _, tb = sys.exc_info()
        traceback.print_tb(tb)  # Fixed format
        tb_info = traceback.extract_tb(tb)
        filename, line, func, text = tb_info[-1]

        print("An error occurred on line {} in statement {}".format(line, text))
        print(msg)
        print(assertMessage)
        assert str(msg) == assertMessage
        print ("Succesful revert")
    
    if not reverted:
        print ("Failed to revert: " + assertMessage)
        assert False