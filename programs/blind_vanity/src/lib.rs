use anchor_lang::prelude::*;

declare_id!("EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6");

#[program]
pub mod blind_vanity {
    use super::*;

    pub fn upload_vanity_package(
        ctx: Context<UploadVanityPackage>,
        vanity_pubkey: Pubkey,
        encrypted_json: Vec<u8>,
    ) -> Result<()> {
        let pkg = &mut ctx.accounts.vanity_package;

        let needed = 8 + 32 + 4 + encrypted_json.len() + 32 + 1;
        let current = pkg.to_account_info().data_len();
        if needed > current {
            let rent = Rent::get()?;
            let new_min = rent.minimum_balance(needed);
            let lamports_diff = new_min.saturating_sub(pkg.to_account_info().lamports());
            if lamports_diff > 0 {
                anchor_lang::system_program::transfer(
                    CpiContext::new(
                        ctx.accounts.system_program.to_account_info(),
                        anchor_lang::system_program::Transfer {
                            from: ctx.accounts.authority.to_account_info(),
                            to: pkg.to_account_info(),
                        },
                    ),
                    lamports_diff,
                )?;
            }
            pkg.to_account_info().realloc(needed, false)?;
        }

        pkg.vanity_pubkey = vanity_pubkey;
        pkg.encrypted_json = encrypted_json;
        pkg.authority = ctx.accounts.authority.key();
        pkg.bump = ctx.bumps.vanity_package;

        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(vanity_pubkey: Pubkey)]
pub struct UploadVanityPackage<'info> {
    #[account(
        init_if_needed,
        payer = authority,
        space = 109,
        seeds = [b"vanity_pkg", vanity_pubkey.as_ref()],
        bump
    )]
    pub vanity_package: Account<'info, VanityPackage>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[account]
pub struct VanityPackage {
    pub vanity_pubkey: Pubkey,
    pub encrypted_json: Vec<u8>,
    pub authority: Pubkey,
    pub bump: u8,
}
