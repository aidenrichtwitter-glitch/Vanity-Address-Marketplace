const { Keypair, PublicKey, Connection, clusterApiUrl } = require('@solana/web3.js');
const bs58 = require('bs58');

// Metaplex Umi
const { createUmi } = require('@metaplex-foundation/umi-bundle-defaults');
const { mplTokenMetadata } = require('@metaplex-foundation/mpl-token-metadata');
const { generateSigner, signerIdentity, percentAmount, createSignerFromKeypair } = require('@metaplex-foundation/umi');
const { createNft, transferV1 } = require('@metaplex-foundation/mpl-token-metadata');

const connection = new Connection(clusterApiUrl('devnet'), 'confirmed');

const sellerKp = Keypair.fromSecretKey(
  bs58.decode("353nea2bn9RSXEP1KhnwucV2F7A4u3XfsqePgTTg9an5rzpfjMs6qMMTw2PBj4wDTTFLzBTSHxhg1zTNd5CyQGza")
);

async function main() {
  console.log("Testing NFT mint + transfer to PDA...");

  const umi = createUmi('https://api.devnet.solana.com').use(mplTokenMetadata());
  const umiSigner = createSignerFromKeypair(umi, sellerKp);
  umi.use(signerIdentity(umiSigner));

  // Create a test PDA (escrow)
  const [testPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("test_escrow"), sellerKp.publicKey.toBuffer()],
    new PublicKey("9GQeitQCcMGp8EsLUtvLWGEbHPK7FhqC5pnbaqRdGHbG")
  );

  console.log("Target escrow PDA:", testPda.toBase58());

  // 1. Mint NFT to your wallet
  const mint = generateSigner(umi);
  const { signature: mintSig } = await createNft(umi, {
    mint,
    name: "Test Blind Vanity NFT",
    uri: "https://arweave.net/placeholder",
    sellerFeeBasisPoints: percentAmount(5),
    payer: umiSigner,
  }).sendAndConfirm(umi);

  console.log(`NFT minted: ${mint.publicKey.toString()}`);
  console.log(`Mint sig: ${bs58.encode(mintSig)}`);

  // 2. Transfer to PDA escrow
  const { signature: transferSig } = await transferV1(umi, {
    mint: mint.publicKey,
    fromOwner: sellerKp.publicKey,
    toOwner: testPda,
    amount: 1,
    payer: umiSigner,
  }).sendAndConfirm(umi);

  console.log(`NFT transferred to escrow PDA: ${testPda.toBase58()}`);
  console.log(`Transfer sig: ${bs58.encode(transferSig)}`);

  console.log("\n✅ Success! NFT is now in escrow.");
}

main().catch(console.error);
