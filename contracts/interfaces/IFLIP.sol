pragma solidity ^0.8.7;


import "@openzeppelin/contracts/token/ERC777/IERC777.sol";


/**
* @title    FLIP interface for the FLIP utility token
* @author   Quantaf1re (James Key)
*/
interface IFLIP is IERC777 {
    function mint(
        address receiver,
        uint amount,
        bytes memory userData,
        bytes memory operatorData
    ) external;
}