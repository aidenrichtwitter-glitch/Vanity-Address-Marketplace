const { Connection, Keypair, PublicKey, Transaction, TransactionInstruction, sendAndConfirmTransaction, SystemProgram } = require('@solana/web3.js');
const bs58 = require('bs58');
const prompt = require('prompt-sync')();

const RPC = 'https://api.devnet.solana.com';
const connection = new Connection(RPC, 'confirmed');
const PROGRAM_ID = new PublicKey("EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6");
const PDA_SEED_PREFIX = Buffer.from("vanity_pkg");

function findPDA(vanityPubkey) {
  return PublicKey.findProgramAddressSync(
    [PDA_SEED_PREFIX, vanityPubkey.toBuffer()],
    PROGRAM_ID
  );
}

async function main() {
  const pdaStr = prompt('Enter PDA address: ').trim();
  const pda = new PublicKey(pdaStr);

  const buyerSecret = prompt('Enter your buyer private key (base58): ').trim();
  const buyerKp = Keypair.fromSecretKey(bs58.decode(buyerSecret));

  console.log(`\nBuyer wallet: ${buyerKp.publicKey.toBase58()}`);
  console.log(`Fetching PDA: ${pda.toBase58()}`);

  const acc = await connection.getAccountInfo(pda);
  if (!acc) {
    console.error('PDA not found on-chain');
    return;
  }

  console.log(`PDA data length: ${acc.data.length} bytes`);
  console.log(`PDA owner: ${acc.owner.toBase58()}`);

  const vanityPubkey = new PublicKey(acc.data.slice(8, 40));
  console.log(`Vanity address: ${vanityPubkey.toBase58()}`);

  const encJsonLenOffset = 40;
  const encJsonLen = acc.data.readUInt32LE(encJsonLenOffset);
  const encJsonData = acc.data.slice(encJsonLenOffset + 4, encJsonLenOffset + 4 + encJsonLen);
  const encJson = JSON.parse(encJsonData.toString('utf8'));

  console.log(`\nPackage found!`);
  console.log(`Vanity Address: ${encJson.vanityAddress || vanityPubkey.toBase58()}`);
  console.log(`Ciphertext length: ${encJson.ciphertext?.length || 0} chars`);
  console.log(`\nThis PDA contains an encrypted vanity keypair.`);
  console.log(`To decrypt, use claim.js or buyer_decrypt.js with this PDA address.`);

  const confirm = prompt('\nProceed to claim? (y/n): ').trim().toLowerCase();
  if (confirm !== 'y') {
    console.log('Cancelled.');
    return;
  }

  console.log('\nUse claim.js to decrypt the vanity keypair from this PDA.');
}

main().catch(console.error);
