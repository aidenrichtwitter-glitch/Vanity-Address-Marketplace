use solana_program::{
    account_info::{next_account_info, AccountInfo},
    entrypoint,
    entrypoint::ProgramResult,
    msg,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

entrypoint!(process_instruction);

const INSTRUCTION_DISC: [u8; 8] = [0xa5, 0x69, 0x67, 0xa8, 0xe5, 0xd6, 0xb1, 0xfb];
const ACCOUNT_DISC: [u8; 8] = [0x18, 0x46, 0x62, 0xBF, 0x3A, 0x90, 0x7B, 0x9E];
const PDA_SEED: &[u8] = b"vanity_pkg";

pub fn process_instruction(
    program_id: &Pubkey,
    accounts: &[AccountInfo],
    instruction_data: &[u8],
) -> ProgramResult {
    if instruction_data.len() < 8 {
        return Err(ProgramError::InvalidInstructionData);
    }
    let disc = &instruction_data[..8];
    if disc != INSTRUCTION_DISC {
        msg!("Unknown instruction discriminator");
        return Err(ProgramError::InvalidInstructionData);
    }

    let data = &instruction_data[8..];
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

    let needed = 8 + 32 + 4 + json_len + 32 + 1;
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

    msg!("Vanity package uploaded: {} bytes", json_len);

    Ok(())
}
