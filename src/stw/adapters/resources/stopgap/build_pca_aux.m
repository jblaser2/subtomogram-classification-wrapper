function build_pca_aux(rootdir, lp_rad, lp_sigma, hp_rad, hp_sigma)
%% build_pca_aux
% Write the PCA auxiliary files required before running STOPGAP PCA:
%   lists/filter_list.star  — one bandpass filter entry
%   pca_settings.txt        — override calc_ctf=0 and calc_exp=0
%
% rootdir  : STOPGAP project root
% lp_rad   : low-pass radius in Fourier pixels  (e.g. 17)
% lp_sigma : low-pass sigma in Fourier pixels   (e.g. 3)
% hp_rad   : high-pass radius in Fourier pixels (e.g. 1)
% hp_sigma : high-pass sigma in Fourier pixels  (e.g. 2)

lists_dir = fullfile(rootdir, 'lists');
if ~exist(lists_dir,'dir'), mkdir(lists_dir); end

% sg_pca_append_filter_list APPENDS to any existing filter_list.star. Re-running
% the pipeline would therefore accumulate duplicate filter rows (n_filt grows by
% 1 per run). That is wrong for our single-bandpass PCA and also triggers a hang:
% with n_filt>1 and n_cores=64, STOPGAP's distribute_filter_jobs.m can orphan the
% last filter (off-by-one truncation), so pca_assemble_ccmatrix never assembles it
% and complete_pca_ccmatrix's wait_for_them blocks forever. Always start fresh so
% n_filt==1 exactly.
filtlist_file = fullfile(lists_dir, 'filter_list.star');
if exist(filtlist_file, 'file')
    delete(filtlist_file);
end
sg_pca_append_filter_list(filtlist_file, ...
    lp_rad, lp_sigma, hp_rad, hp_sigma);
fprintf('[pca_aux] wrote filter_list.star (lp_rad=%d lp_sig=%d hp_rad=%d hp_sig=%d)\n', ...
        lp_rad, lp_sigma, hp_rad, hp_sigma);

% Override CTF and exposure weighting (only tilt range known for this dataset)
fid = fopen(fullfile(rootdir, 'pca_settings.txt'), 'w');
if fid == -1
    error('ACHTUNG!!! Cannot write pca_settings.txt to %s', rootdir);
end
fprintf(fid, 'calc_ctf=0\ncalc_exp=0\n');
fclose(fid);
fprintf('[pca_aux] wrote pca_settings.txt (calc_ctf=0, calc_exp=0)\n');
end
