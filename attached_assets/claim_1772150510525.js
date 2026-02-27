const { Connection, PublicKey } = require('@solana/web3.js');
const bs58 = require('bs58');
const { LitNodeClient } = require('@lit-protocol/lit-node-client');
const prompt = require('prompt-sync')();
const fs = require('fs');
const path = require('path');
const nacl = require('tweetnacl');
const { Keypair } = require('@solana/web3.js');

const RPC = 'https://api.devnet.solana.com';
const OUTPUT_DIR = './claimed_vanity';

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

  const data = acc.data;

  // Search for JSON
  const search = '{"ciphertext';
  let start = -1;
  for (let i = 0; i < data.length - search.length; i++) {
    if (data.slice(i, i + search.length).toString() === search) {
      start = i;
      break;
    }
  }

  if (start === -1) {
    console.error('Could not find JSON data');
    return;
  }

  let jsonStr = new TextDecoder().decode(data.slice(start));
  if (!jsonStr.endsWith('}')) {
    const last = jsonStr.lastIndexOf('}');
    if (last > 0) jsonStr = jsonStr.slice(0, last + 1);
  }

  const pkg = JSON.parse(jsonStr);
  const { ciphertext, dataToEncryptHash, vanityAddress, nftMint } = pkg;

  console.log(`\nVanity Address: ${vanityAddress}`);
  console.log(`NFT Mint: ${nftMint}`);

  const lit = new LitNodeClient({ litNetwork: 'datil' });
  await lit.connect();

  console.log("\nDecrypting... (using your wallet authSig)");

  // Replace this with real wallet later
  const testKp = Keypair.generate();
  const message = `Lit auth ${Date.now()}`;
  const signature = nacl.sign.detached(new TextEncoder().encode(message), testKp.secretKey);

  const authSig = {
    sig: bs58.encode(signature),
    derivedVia: "solana.signMessage",
    signedMessage: message,
    address: testKp.publicKey.toBase58(),
  };

  try {
    const result = await lit.decrypt({
      ciphertext,
      dataToEncryptHash,
      chain: "solanaDevnet",
      authSig,
    });

    const privBase58 = new TextDecoder().decode(result.decryptedData);

    console.log('\n' + '='.repeat(80));
    console.log('🎉 DECRYPTION SUCCESS!');
    console.log(`Address: ${vanityAddress}`);
    console.log(`Private Key: ${privBase58}`);
    console.log('='.repeat(80));

  } catch (e) {
    console.error("Decryption failed:", e.message);
  }
}

main().catch(console.error);
