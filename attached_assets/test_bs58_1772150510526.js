const bs58 = require('bs58');

const str = "353nea2bn9RSXEP1KhnwucV2F7A4u3XfsqePgTTg9an5rzpfjMs6qMMTw2PBj4wDTTFLzBTSHxhg1zTNd5CyQGza";

try {
  const decoded = bs58.decode(str);
  console.log("Decoded length:", decoded.length);
  console.log("First 5 bytes:", decoded.slice(0,5));
} catch (e) {
  console.log("Error:", e.message);
}
