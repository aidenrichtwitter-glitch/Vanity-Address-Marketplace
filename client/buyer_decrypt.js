const { Connection, clusterApiUrl, PublicKey, Keypair } = require('@solana/web3.js');
const { LitNodeClient } = require('@lit-protocol/lit-node-client');
const bs58 = require('bs58');
const nacl = require('tweetnacl');
const prompt = require('prompt-sync')();

const connection = new Connection(clusterApiUrl('devnet'), 'confirmed');
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
  const PDA = new PublicKey(pdaStr);

  console.log(`Fetching package from PDA: ${PDA.toBase58()}...`);
  const account = await connection.getAccountInfo(PDA, 'confirmed');

  if (!account || account.data.length < 100) {
    console.log("No package found at this PDA");
    return;
  }

  const vanityPubkey = new PublicKey(account.data.slice(8, 40));
  console.log(`Vanity address: ${vanityPubkey.toBase58()}`);

  const encJsonLen = account.data.readUInt32LE(40);
  const encJsonData = account.data.slice(44, 44 + encJsonLen);
  const litData = JSON.parse(encJsonData.toString('utf8'));

  console.log("Package found. Preparing to decrypt...");

  const buyerSecret = prompt('Enter your wallet private key (base58): ').trim();
  const buyerKp = Keypair.fromSecretKey(bs58.decode(buyerSecret));
  console.log(`Using wallet: ${buyerKp.publicKey.toBase58()}`);

  const litNodeClient = new LitNodeClient({ litNetwork: 'datil' });
  await litNodeClient.connect();

  const message = `Lit Protocol auth ${Date.now()}`;
  const messageBytes = new TextEncoder().encode(message);
  const signature = nacl.sign.detached(messageBytes, buyerKp.secretKey);

  const authSig = {
    sig: bs58.encode(signature),
    derivedVia: "solana.signMessage",
    signedMessage: message,
    address: buyerKp.publicKey.toBase58(),
  };

  console.log("Decrypting with Lit Protocol (datil network)...");

  try {
    const result = await litNodeClient.decrypt({
      ciphertext: litData.ciphertext,
      dataToEncryptHash: litData.dataToEncryptHash,
      accessControlConditions: ACCESS_CONTROL_CONDITIONS,
      chain: "solanaDevnet",
      authSig,
    });

    const privBase58 = new TextDecoder().decode(result.decryptedData);
    console.log("\n" + "=".repeat(60));
    console.log("DECRYPT SUCCESS!");
    console.log(`Vanity Address: ${litData.vanityAddress || vanityPubkey.toBase58()}`);
    console.log(`Private Key: ${privBase58}`);
    console.log("=".repeat(60));
    console.log("\nImport this key into Phantom / Solflare to own the vanity address!");
  } catch (e) {
    console.error("Decryption failed:", e.message);
    console.error("Ensure your wallet has > 0 SOL on devnet.");
  }
}

main().catch(e => console.error("Error:", e.message));
