// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

interface IAddressHolder {
    event StateChainGatewayUpdated(address oldStateChainGateway, address newStateChainGateway);
    event StakingAddressesUpdated(
        address oldStFLIP,
        address oldStMinter,
        address oldStBurner,
        address oldStAggregator,
        address newStFLIP,
        address newStMinter,
        address newStBurner,
        address newStAggregator
    );
    event GovernorTransferred(address oldGovernor, address newGovernor);

    //////////////////////////////////////////////////////////////
    //                                                          //
    //                  State-changing functions                //
    //                                                          //
    //////////////////////////////////////////////////////////////

    function updateStateChainGateway(address _stateChainGateway) external;

    function updateStakingAddresses(address _stMinter, address _stBurner, address _stFLIP, address _stAggregator) external;

    function transferGovernor(address _governor) external;

    //////////////////////////////////////////////////////////////
    //                                                          //
    //                Non-state-changing functions              //
    //                                                          //
    //////////////////////////////////////////////////////////////

    function getStateChainGateway() external view returns (address);

    function getStakingAddress() external view returns (address);

    function getUnstakingAddresses() external view returns (address, address);

    function getAggregatorAddress() external view returns (address);

    function getGovernor() external view returns (address);
}
