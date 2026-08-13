% dpkpca_embed.m -- env-driven Dynamo dpkpca EMBEDDING step for stw's Dynamo
% adapter. Computes the eigencomponents (deterministic, seed-independent) and
% saves them to <OUTDIR>/eigencomponents.csv. k-means clustering is done
% downstream in Python (stw.adapters.dynamo), once per (k, seed), on the
% cached eigencomponents -- see that module's docstring for why.
%
% Required env vars:
%   DYNAMO_ACTIVATE  path to dynamo_activate.m
%   DPKPCA_OUTDIR    embedding cache dir (also cwd; holds data/, .tbl, workflow)
%   DPKPCA_TBL       identity-pose Dynamo table
%   DPKPCA_DATA      dir of particle_NNNNN.mrc symlinks
%   DPKPCA_MASK      mask .mrc (read directly, no format conversion needed)
%   DPKPCA_WFNAME    workflow name (subdir of OUTDIR, actually created as
%                    "<WFNAME>.PCA" by dpkpca.new -- callers should not assume
%                    the bare name is the real directory)

run(getenv('DYNAMO_ACTIVATE'));
setenv('MW_SERVICE_HOST_DISABLE', '1');

OUTDIR = getenv('DPKPCA_OUTDIR');
TBL    = getenv('DPKPCA_TBL');
DATA   = getenv('DPKPCA_DATA');
MASK   = getenv('DPKPCA_MASK');
WFNAME = getenv('DPKPCA_WFNAME');

cd(OUTDIR);
fprintf('\n=== dpkpca embedding: %s (%s) ===\n', WFNAME, datestr(now,'HH:MM:SS'));
mask = dynamo_read(MASK);
n_active = sum(mask(:) > 0.5);
n_total = numel(mask);
active_frac = n_active / n_total;
fprintf('Mask active voxels (>0.5): %d / %d (%.1f%%)\n', n_active, n_total, 100*active_frac);

% Real, machine-crashing bug found in the source project (ram-oom-dynamo-parpool-nomask):
% each parpool worker holds a full per-particle vector sized by the mask's ACTIVE VOXEL
% COUNT, not a fixed box size -- an unmasked/near-full-box mask with the default cores='*'
% (24 workers on that machine) drove system RAM from 11GB to 58GB in under a minute and
% crashed the whole session. Cap workers explicitly, scaling down further for a wide-open mask.
if active_frac > 0.5
    n_workers = 2;
elseif active_frac > 0.15
    n_workers = 4;
else
    n_workers = 8;
end
fprintf('Using explicit parpool cap: %d workers (active_frac=%.3f)\n', n_workers, active_frac);

wb = dpkpca.new(WFNAME, 't', TBL, 'd', DATA, 'm', mask);
wb.setBand([0.05, 0.45, 2]);
wb.setSym('c1');
wb.settings.general.bin.value = 0;
wb.settings.computing.cores.value = n_workers;
wb.settings.computing.useGpus.value = false;
wb.setBatch(100);
wb.unfold();

% prealign/ccmatrix are load-bearing (ccmatrix hard-requires prealign's output -- confirmed
% directly, skipping prealign makes ccmatrix throw); a benign warning has been observed from
% eigentable ("Brace indexing is not supported...") that does not stop it from completing
% correctly, so only prealign/ccmatrix failures are treated as fatal here, matching the
% source project's own established try/catch pattern.
steps = {'prealign', 'ccmatrix', 'eigentable', 'eigenvolumes'};
for i = 1:numel(steps)
    s = steps{i};
    fprintf('\n=== STEP %s (%s) ===\n', s, datestr(now,'HH:MM:SS'));
    try
        wb.steps.items.(s).compute();
        fprintf('=== STEP_OK %s ===\n', s);
    catch ME
        fprintf('=== STEP_FAIL %s : %s ===\n', s, ME.message);
        if strcmp(s,'ccmatrix') || strcmp(s,'prealign'); exit(1); end
    end
end

E = wb.getEigencomponents();
writematrix(E, fullfile(OUTDIR, 'eigencomponents.csv'));
fprintf('\nEigencomponents saved: %dx%d -> eigencomponents.csv\n', size(E,1), size(E,2));
fprintf('=== EMBED_DONE (%s) ===\n', datestr(now,'HH:MM:SS'));
