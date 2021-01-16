pragma solidity ^0.7.0;


interface IERC20Lite {
    function transfer(address recipient, uint256 amount) external returns (bool);
}


/**
* @title    DepositToken contract
* @notice   Creates a contract with a known address and withdraws tokens (and ETH) from it
* @author   Quantaf1re (James Key)
*/
contract DepositToken {

    constructor(address tokenAddr, uint amount) {
        IERC20Lite(tokenAddr).transfer(msg.sender, amount);
        // This contract should only have been created if there's
        // already enough Eth here. This will also send any excess
        // that the user mistakenly sent
        selfdestruct(msg.sender);
    }

}