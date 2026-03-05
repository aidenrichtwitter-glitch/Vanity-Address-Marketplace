use solana_program::{
    account_info::{next_account_info, AccountInfo},
    entrypoint,
    entrypoint::ProgramResult,
    instruction::Instruction,
    msg,
    program::invoke,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

entrypoint!(process_instruction);

const UPLOAD_DISC: [u8; 8] = [0xa5, 0x69, 0x67, 0xa8, 0xe5, 0xd6, 0xb1, 0xfb];
const BUY_DISC: [u8; 8] = [0xb2, 0x7a, 0x78, 0xb9, 0xf6, 0xe7, 0xc2, 0x0c];
const ACCOUNT_DISC: [u8; 8] = [0x18, 0x46, 0x62, 0xBF, 0x3A, 0x90, 0x7B, 0x9E];
const PDA_SEED: &[u8] = b"vanity_pkg";

const TOKEN_PROGRAM_ID_BYTES: [u8; 32] = [
    6, 221, 246, 225, 215, 101, 161, 147, 217, 203, 225, 70, 206, 235, 121, 172,
    28, 180, 133, 237, 95, 91, 55, 145, 58, 140, 245, 133, 126, 255, 0, 169,
];

const ATA_PROGRAM_ID_BYTES: [u8; 32] = [
    140, 151, 37, 143, 78, 36, 137, 241, 187, 61, 16, 41, 20, 142, 13, 131,
    11, 90, 19, 153, 218, 255, 16, 132, 4, 142, 123, 216, 219, 233, 248, 89,
];

pub fn process_instruction(
    program_id: &Pubkey,
    accounts: &[AccountInfo],
    instruction_data: &[u8],
) -> ProgramResult {
    if instruction_data.len() < 8 {
        return Err(ProgramError::InvalidInstructionData);
    }
    let disc = &instruction_data[..8];

    if disc == UPLOAD_DISC {
        process_upload(program_id, accounts, &instruction_data[8..])
    } else if disc == BUY_DISC {
        process_buy(program_id, accounts, &instruction_data[8..])
    } else {
        msg!("Unknown instruction discriminator");
        Err(ProgramError::InvalidInstructionData)
    }
}

fn process_upload(
    program_id: &Pubkey,
    accounts: &[AccountInfo],
    data: &[u8],
) -> ProgramResult {
    if data.len() < 36 {
        return Err(ProgramError::InvalidInstructionData);
    }

    let vanity_pubkey = Pubkey::try_from(&data[..32])
        .map_err(|_| ProgramError::InvalidInstructionData)?;
    let json_len = u32::from_le_bytes(
        data[32..36].try_into().map_err(|_| ProgramError::InvalidInstructionData)?
    ) as usize;

    if data.len() < 36 + json_len {
        return Err(ProgramError::InvalidInstructionData);
    }
    let json_bytes = &data[36..36 + json_len];

    let price_lamports: u64 = if data.len() >= 36 + json_len + 8 {
        u64::from_le_bytes(
            data[36 + json_len..36 + json_len + 8]
                .try_into()
                .map_err(|_| ProgramError::InvalidInstructionData)?,
        )
    } else {
        0
    };

    let account_iter = &mut accounts.iter();
    let pda_info = next_account_info(account_iter)?;
    let authority_info = next_account_info(account_iter)?;
    let system_info = next_account_info(account_iter)?;

    if !authority_info.is_signer {
        return Err(ProgramError::MissingRequiredSignature);
    }

    if *system_info.key != solana_program::system_program::ID {
        msg!("Invalid system program");
        return Err(ProgramError::IncorrectProgramId);
    }

    let (expected_pda, bump) =
        Pubkey::find_program_address(&[PDA_SEED, vanity_pubkey.as_ref()], program_id);
    if *pda_info.key != expected_pda {
        msg!("PDA mismatch");
        return Err(ProgramError::InvalidArgument);
    }

    let needed = 8 + 32 + 4 + json_len + 32 + 1 + 8;
    let signer_seeds: &[&[u8]] = &[PDA_SEED, vanity_pubkey.as_ref(), &[bump]];

    if pda_info.data_len() == 0 {
        let rent = Rent::get()?;
        let lamports = rent.minimum_balance(needed);
        invoke_signed(
            &system_instruction::create_account(
                authority_info.key,
                pda_info.key,
                lamports,
                needed as u64,
                program_id,
            ),
            &[authority_info.clone(), pda_info.clone(), system_info.clone()],
            &[signer_seeds],
        )?;
    } else {
        if pda_info.owner != program_id {
            return Err(ProgramError::IllegalOwner);
        }
        let current_len = pda_info.data_len();
        if current_len < needed {
            let rent = Rent::get()?;
            let new_min = rent.minimum_balance(needed);
            let current_lamports = pda_info.lamports();
            let diff = new_min.saturating_sub(current_lamports);
            if diff > 0 {
                invoke_signed(
                    &system_instruction::transfer(authority_info.key, pda_info.key, diff),
                    &[authority_info.clone(), pda_info.clone(), system_info.clone()],
                    &[signer_seeds],
                )?;
            }
            pda_info.realloc(needed, false)?;
        }
    }

    let mut account_data = pda_info.try_borrow_mut_data()?;
    let mut offset = 0;

    account_data[offset..offset + 8].copy_from_slice(&ACCOUNT_DISC);
    offset += 8;

    account_data[offset..offset + 32].copy_from_slice(vanity_pubkey.as_ref());
    offset += 32;

    account_data[offset..offset + 4].copy_from_slice(&(json_len as u32).to_le_bytes());
    offset += 4;

    account_data[offset..offset + json_len].copy_from_slice(json_bytes);
    offset += json_len;

    account_data[offset..offset + 32].copy_from_slice(authority_info.key.as_ref());
    offset += 32;

    account_data[offset] = bump;
    offset += 1;

    account_data[offset..offset + 8].copy_from_slice(&price_lamports.to_le_bytes());

    msg!("Vanity package uploaded: {} bytes, price={}", json_len, price_lamports);

    Ok(())
}

fn process_buy(
    program_id: &Pubkey,
    accounts: &[AccountInfo],
    data: &[u8],
) -> ProgramResult {
    if data.len() < 32 {
        return Err(ProgramError::InvalidInstructionData);
    }

    let vanity_pubkey = Pubkey::try_from(&data[..32])
        .map_err(|_| ProgramError::InvalidInstructionData)?;

    let account_iter = &mut accounts.iter();
    let pda_info = next_account_info(account_iter)?;
    let buyer_info = next_account_info(account_iter)?;
    let seller_info = next_account_info(account_iter)?;
    let _mint_info = next_account_info(account_iter)?;
    let pda_ata_info = next_account_info(account_iter)?;
    let buyer_ata_info = next_account_info(account_iter)?;
    let token_program_info = next_account_info(account_iter)?;
    let system_program_info = next_account_info(account_iter)?;
    let ata_program_info = next_account_info(account_iter)?;

    if !buyer_info.is_signer {
        msg!("Buyer must sign");
        return Err(ProgramError::MissingRequiredSignature);
    }

    let token_program_id = Pubkey::new_from_array(TOKEN_PROGRAM_ID_BYTES);
    if *token_program_info.key != token_program_id {
        msg!("Invalid token program");
        return Err(ProgramError::IncorrectProgramId);
    }

    if *system_program_info.key != solana_program::system_program::ID {
        msg!("Invalid system program");
        return Err(ProgramError::IncorrectProgramId);
    }

    let ata_program_id = Pubkey::new_from_array(ATA_PROGRAM_ID_BYTES);
    if *ata_program_info.key != ata_program_id {
        msg!("Invalid ATA program");
        return Err(ProgramError::IncorrectProgramId);
    }

    let (expected_pda, bump) =
        Pubkey::find_program_address(&[PDA_SEED, vanity_pubkey.as_ref()], program_id);
    if *pda_info.key != expected_pda {
        msg!("PDA mismatch");
        return Err(ProgramError::InvalidArgument);
    }

    if pda_info.owner != program_id {
        msg!("PDA not owned by program");
        return Err(ProgramError::IllegalOwner);
    }

    let account_data = pda_info.try_borrow_data()?;
    if account_data.len() < 8 + 32 + 4 {
        msg!("PDA data too short");
        return Err(ProgramError::InvalidAccountData);
    }

    if account_data[..8] != ACCOUNT_DISC {
        msg!("Invalid PDA discriminator");
        return Err(ProgramError::InvalidAccountData);
    }

    let json_len = u32::from_le_bytes(
        account_data[40..44].try_into().map_err(|_| ProgramError::InvalidAccountData)?
    ) as usize;

    let min_len = 8 + 32 + 4 + json_len + 32 + 1 + 8;
    if account_data.len() < min_len {
        msg!("PDA data missing price field (legacy package)");
        return Err(ProgramError::InvalidAccountData);
    }

    let authority_offset = 44 + json_len;
    let stored_authority = Pubkey::try_from(&account_data[authority_offset..authority_offset + 32])
        .map_err(|_| ProgramError::InvalidAccountData)?;

    if *seller_info.key != stored_authority {
        msg!("Seller mismatch: expected {}", stored_authority);
        return Err(ProgramError::InvalidArgument);
    }

    let price_offset = authority_offset + 32 + 1;
    let price_lamports = u64::from_le_bytes(
        account_data[price_offset..price_offset + 8]
            .try_into()
            .map_err(|_| ProgramError::InvalidAccountData)?,
    );

    drop(account_data);

    if price_lamports > 0 {
        msg!("Transferring {} lamports to seller", price_lamports);
        invoke(
            &system_instruction::transfer(buyer_info.key, seller_info.key, price_lamports),
            &[buyer_info.clone(), seller_info.clone(), system_program_info.clone()],
        )?;
    }

    let buyer_ata_data = buyer_ata_info.try_borrow_data()?;
    let buyer_ata_exists = buyer_ata_data.len() > 0;
    drop(buyer_ata_data);

    if !buyer_ata_exists {
        msg!("Creating buyer ATA");
        let create_ata_ix = Instruction {
            program_id: ata_program_id,
            accounts: vec![
                solana_program::instruction::AccountMeta::new(*buyer_info.key, true),
                solana_program::instruction::AccountMeta::new(*buyer_ata_info.key, false),
                solana_program::instruction::AccountMeta::new_readonly(*buyer_info.key, false),
                solana_program::instruction::AccountMeta::new_readonly(*_mint_info.key, false),
                solana_program::instruction::AccountMeta::new_readonly(solana_program::system_program::ID, false),
                solana_program::instruction::AccountMeta::new_readonly(token_program_id, false),
            ],
            data: vec![1],
        };
        invoke(
            &create_ata_ix,
            &[
                buyer_info.clone(),
                buyer_ata_info.clone(),
                buyer_info.clone(),
                _mint_info.clone(),
                system_program_info.clone(),
                token_program_info.clone(),
            ],
        )?;
    }

    msg!("Transferring NFT from PDA to buyer");
    let mut transfer_data = vec![3u8];
    transfer_data.extend_from_slice(&1u64.to_le_bytes());

    let transfer_ix = Instruction {
        program_id: token_program_id,
        accounts: vec![
            solana_program::instruction::AccountMeta::new(*pda_ata_info.key, false),
            solana_program::instruction::AccountMeta::new(*buyer_ata_info.key, false),
            solana_program::instruction::AccountMeta::new_readonly(*pda_info.key, true),
        ],
        data: transfer_data,
    };

    let signer_seeds: &[&[u8]] = &[PDA_SEED, vanity_pubkey.as_ref(), &[bump]];
    invoke_signed(
        &transfer_ix,
        &[pda_ata_info.clone(), buyer_ata_info.clone(), pda_info.clone()],
        &[signer_seeds],
    )?;

    msg!("Buy complete: NFT transferred to buyer");

    Ok(())
}
