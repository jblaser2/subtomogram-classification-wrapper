function build_wedgelist(rootdir, min_tilt, max_tilt, tilt_step)
%% build_wedgelist
% Build a STOPGAP wedgelist from tilt range only (CTF and exposure off).
% Reads tomogram numbers from meta/tomo_nums.csv (written by build_inputs).
% Reads pixel size and box size from the first subtomogram MRC header.
%
% rootdir  : STOPGAP project root
% min_tilt : minimum tilt angle in degrees (e.g. -60)
% max_tilt : maximum tilt angle in degrees (e.g.  60)
% tilt_step: tilt increment in degrees       (e.g.   3)

tomos = readmatrix(fullfile(rootdir, 'meta', 'tomo_nums.csv'));
tomos = tomos(:);   % ensure column vector

h  = sg_read_mrc_header(fullfile(rootdir, 'subtomograms', 'subtomo_1.mrc'));
px  = double(h.xlen) / double(h.mx);   % Å/vox = cell length / grid sampling
box = double(h.nx);
fprintf('[build_wedge] pixel size = %.4f Å/vox, box = %d px\n', px, box);

tilts   = (min_tilt : tilt_step : max_tilt)';
n_tilts = numel(tilts);
n_tomos = numel(tomos);

% One entry per tomo × tilt (scalar fields; CTF/exposure fields are zeros)
k = 0;
wl(n_tomos * n_tilts) = struct('tomo_num',[],'pixelsize',[],'tomo_x',[],...
    'tomo_y',[],'tomo_z',[],'z_shift',[],'tilt_angle',[],...
    'defocus',[],'exposure',[],'voltage',[],'amp_contrast',[],'cs',[]);

for ti = 1:n_tomos
    for j = 1:n_tilts
        k = k + 1;
        wl(k).tomo_num     = tomos(ti);
        wl(k).pixelsize    = px;
        wl(k).tomo_x       = box;
        wl(k).tomo_y       = box;
        wl(k).tomo_z       = box;
        wl(k).z_shift      = 0;
        wl(k).tilt_angle   = tilts(j);
        wl(k).defocus      = 0;    % unused (calc_ctf=0)
        wl(k).exposure     = 0;    % unused (calc_exp=0)
        wl(k).voltage      = 300;
        wl(k).amp_contrast = 0.07;
        wl(k).cs           = 2.7;
    end
end

sg_wedgelist_write(fullfile(rootdir, 'lists', 'wedgelist.star'), wl);
fprintf('[build_wedge] wrote %d entries (%d tomos x %d tilts) to lists/wedgelist.star\n', ...
        k, n_tomos, n_tilts);
end
