const go = async () => {
  const privateKey = jsParams.privateKey;
  const vanityAddress = jsParams.vanityAddress;
  const accessControlConditions = jsParams.accessControlConditions;

  if (!privateKey || !vanityAddress) {
    Lit.Actions.setResponse({
      response: JSON.stringify({ error: "Missing privateKey or vanityAddress" }),
    });
    return;
  }

  const { ciphertext, dataToEncryptHash } = await Lit.Actions.encrypt({
    accessControlConditions: accessControlConditions,
    to_encrypt: new TextEncoder().encode(privateKey),
  });

  Lit.Actions.setResponse({
    response: JSON.stringify({
      ciphertext: ciphertext,
      dataToEncryptHash: dataToEncryptHash,
      vanityAddress: vanityAddress,
      accessControlConditions: accessControlConditions,
      encryptedInTEE: true,
    }),
  });
};

go();
