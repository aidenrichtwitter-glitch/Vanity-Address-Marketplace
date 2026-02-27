use anchor_lang::prelude::*;

declare_id!("5saJBeNvrbQ4WcVueFietuBxAixnV1u8StXUriXUuFj5");

#[program]
pub mod blind_vanity {
    use super::*;

    pub fn upload_vanity_package(
        ctx: Context<UploadVanityPackage>,
        vanity_pubkey: Pubkey,
        encrypted_json: Vec<u8>,
    ) -> Result<()> {
        let pkg = &mut ctx.accounts.package;

        let needed = 8 + 32 + 4 + encrypted_json.len() + 32 + 1;

        let current_len = pkg.to_account_info().data_len();
        if current_len < needed {
            let rent = Rent::get()?;
            let new_min = rent.minimum_balance(needed);
            let current_lamports = pkg.to_account_info().lamports();
            let diff = new_min.saturating_sub(current_lamports);
            if diff > 0 {
                anchor_lang::system_program::transfer(
                    CpiContext::new(
                        ctx.accounts.system_program.to_account_info(),
                        anchor_lang::system_program::Transfer {
                            from: ctx.accounts.authority.to_account_info(),
                            to: pkg.to_account_info(),
                        },
                    ),
                    diff,
                )?;
            }
            pkg.to_account_info().realloc(needed, false)?;
        }

        pkg.vanity_pubkey = vanity_pubkey;
        pkg.encrypted_json = encrypted_json;
        pkg.authority = ctx.accounts.authority.key();
        pkg.bump = ctx.bumps.package;

        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(vanity_pubkey: Pubkey, encrypted_json: Vec<u8>)]
pub struct UploadVanityPackage<'info> {
    #[account(
        init_if_needed,
        payer = authority,
        space = 8 + 32 + 4 + encrypted_json.len() + 32 + 1,
        seeds = [b"vanity_pkg", vanity_pubkey.as_ref()],
        bump,
    )]
    pub package: Account<'info, VanityPackage>,
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
