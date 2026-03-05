const { Connection, PublicKey, Keypair } = require('@solana/web3.js');
const bs58 = require('bs58');
const { LitNodeClient } = require('@lit-protocol/lit-node-client');
const prompt = require('prompt-sync')();
const nacl = require('tweetnacl');

const RPC = 'https://api.devnet.solana.com';
const PROGRAM_ID = new PublicKey("EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6");

const ACCESS_CONTROL_CONDITIONS = [
  {
    conditionType: "solRpc",
    method: "getBalance",
    params: [":userAddress"],
    chain: "solanaDevnet",
    returnValueTest: { key: "", comparator: ">", value: "0" },
    contractAddress: "",
    standardContractType: "",
  }
];

async function main() {
  const pdaStr = prompt('Enter PDA address: ').trim();
  const pda = new PublicKey(pdaStr);

  console.log(`Fetching from PDA: ${pda.toBase58()}`);

  const connection = new Connection(RPC, 'confirmed');
  const acc = await connection.getAccountInfo(pda);
  if (!acc) {
    console.error('PDA not found');
    return;
  }

  console.log(`PDA data: ${acc.data.length} bytes`);

  const vanityPubkey = new PublicKey(acc.data.slice(8, 40));
  console.log(`Vanity address: ${vanityPubkey.toBase58()}`);

  const encJsonLenOffset = 40;
  const encJsonLen = acc.data.readUInt32LE(encJsonLenOffset);
  const encJsonData = acc.data.slice(encJsonLenOffset + 4, encJsonLenOffset + 4 + encJsonLen);
  const pkg = JSON.parse(encJsonData.toString('utf8'));

  const { ciphertext, dataToEncryptHash, vanityAddress } = pkg;
  console.log(`\nVanity Address: ${vanityAddress || vanityPubkey.toBase58()}`);

  const buyerSecret = prompt('Enter your wallet private key (base58) for Lit auth: ').trim();
  const buyerKp = Keypair.fromSecretKey(bs58.decode(buyerSecret));
  console.log(`Using wallet: ${buyerKp.publicKey.toBase58()}`);

  const lit = new LitNodeClient({ litNetwork: 'datil' });
  await lit.connect();

  console.log("\nDecrypting with Lit Protocol...");

  const message = `Lit Protocol auth for Solana vanity marketplace ${Date.now()}`;
  const messageBytes = new TextEncoder().encode(message);
  const signature = nacl.sign.detached(messageBytes, buyerKp.secretKey);

  const authSig = {
    sig: bs58.encode(signature),
    derivedVia: "solana.signMessage",
    signedMessage: message,
    address: buyerKp.publicKey.toBase58(),
  };

  try {
    const result = await lit.decrypt({
      ciphertext,
      dataToEncryptHash,
      accessControlConditions: ACCESS_CONTROL_CONDITIONS,
      chain: "solanaDevnet",
      authSig,
    });

    const privBase58 = new TextDecoder().decode(result.decryptedData);

    console.log('\n' + '='.repeat(80));
    console.log('DECRYPTION SUCCESS!');
    console.log(`Vanity Address: ${vanityAddress || vanityPubkey.toBase58()}`);
    console.log(`Private Key: ${privBase58}`);
    console.log('='.repeat(80));
    console.log('\nImport this private key into Phantom or Solflare to use the vanity address.');

  } catch (e) {
    console.error("Decryption failed:", e.message);
    console.error("Make sure your wallet has > 0 SOL on devnet to meet the access condition.");
  }
}

main().catch(console.error);
