const { Connection, clusterApiUrl, PublicKey } = require('@solana/web3.js');
const { LitNodeClient } = require('@lit-protocol/lit-node-client');

const connection = new Connection(clusterApiUrl('devnet'), 'confirmed');
const litNodeClient = new LitNodeClient({ litNetwork: 'datil' });

// YOUR PDA (hardcoded for instant run)
const PDA = new PublicKey("5tjD9wZEaEpQh4ndgnnpHNt8apEYdy7fw3P3v1iyAA3c");

async function main() {
  console.log("Fetching Lit package...");
  const account = await connection.getAccountInfo(PDA, 'confirmed');

  if (!account || account.data.length < 100) {
    console.log("❌ No package found");
    return;
  }

  const length = account.data.readUInt32LE(72);
  const dataStr = account.data.slice(76, 76 + length).toString('utf8').trim();
  const litData = JSON.parse(dataStr);

  console.log("Decrypting with matching dummy authSig...");

  await litNodeClient.connect();

  const authSig = {
    sig: "0x0000000000000000000000000000000000000000000000000000000000000000",
    derivedVia: "web3.eth.personal.sign",
    signedMessage: "dummy message",
    address: "56XB5W3RvFCp5LFyyo7dwJpNk2X98xJb8rzF2Dabroad"
  };

  const result = await litNodeClient.decrypt({
    ciphertext: litData.ciphertext,
    dataToEncryptHash: litData.dataToEncryptHash,
    accessControlConditions: [
      {
        conditionType: "solRpc",
        method: "getBalance",
        params: [":userAddress"],
        chain: "solanaDevnet",
        returnValueTest: { key: "", comparator: ">", value: "0" },
        contractAddress: "",
        standardContractType: ""
      }
    ],
    chain: "solanaDevnet",
    authSig
  });

  const privBase58 = new TextDecoder().decode(result.decryptedData);
  console.log("\n✅ DECRYPT SUCCESS!");
  console.log("Vanity Private Key:", privBase58);
  console.log("\nImport this key into Phantom / Solflare — you own the vanity address!");
}

main().catch(e => console.error("Error:", e.message, "\nFull error:", e));
