const { Connection, Keypair, PublicKey, Transaction, sendAndConfirmTransaction, SystemProgram, TransactionInstruction } = require('@solana/web3.js');
const bs58 = require('bs58');
const prompt = require('prompt-sync')();

const RPC = 'https://api.devnet.solana.com';
const connection = new Connection(RPC, 'confirmed');
const PROGRAM_ID = new PublicKey("9GQeitQCcMGp8EsLUtvLWGEbHPK7FhqC5pnbaqRdGHbG");

async function main() {
  const pdaStr = prompt('Enter PDA address: ').trim();
  const pda = new PublicKey(pdaStr);

  const buyerSecret = prompt('Enter your buyer private key (base58): ').trim();
  const buyerKp = Keypair.fromSecretKey(bs58.decode(buyerSecret));

  const grinder = new PublicKey("EHCbW8MjYdz8dbxwwuDLYg1rMAVXUFY5iyzi8mwEpk8N"); // grinder wallet
  const platform = new PublicKey("PLATFORM_WALLET_ADDRESS"); // replace with your platform wallet address

  // Fetch the package data to get price, nft_mint, etc.
  const acc = await connection.getAccountInfo(pda);
  // Parse package data (adjust slicing based on your struct)
  // For now, assume price_sol is 0.121
  const price_lamports = 0.121 * 1_000_000_000;

  // Assume escrow_token and buyer_token (you need to create buyer token account if not exists)
  const nftMint = new PublicKey("NFT_MINT_FROM_PACKAGE"); // replace with real from package
  const escrow_token = Token.getAssociatedTokenAddress(
    TOKEN_PROGRAM_ID,
    nftMint,
    pda
  );
  const buyer_token = Token.getAssociatedTokenAddress(
    TOKEN_PROGRAM_ID,
    nftMint,
    buyerKp.publicKey
  );

  const ix = new TransactionInstruction({
    keys: [
      { pubkey: buyerKp.publicKey, isSigner: true, isWritable: true },
      { pubkey: pda, isSigner: false, isWritable: true },
      { pubkey: grinder, isSigner: false, isWritable: true },
      { pubkey: platform, isSigner: false, isWritable: true },
      { pubkey: escrow_token, isSigner: false, isWritable: true },
      { pubkey: buyer_token, isSigner: false, isWritable: true },
      { pubkey: TOKEN_PROGRAM_ID, isSigner: false, isWritable: false },
    ],
    programId: PROGRAM_ID,
    data: Buffer.from([]),  // Buy has no data, but if it does, add it here
  });

  const tx = new Transaction().add(ix);
  tx.recentBlockhash = (await connection.getLatestBlockhash()).blockhash;
  tx.feePayer = buyerKp.publicKey;
  tx.sign(buyerKp);

  const sig = await sendAndConfirmTransaction(connection, tx, [buyerKp]);
  console.log("Buy signature:", sig);

  console.log("\n=== BUY SUCCESS ===");
  console.log("NFT transferred to your wallet!");
}

main().catch(console.error);
