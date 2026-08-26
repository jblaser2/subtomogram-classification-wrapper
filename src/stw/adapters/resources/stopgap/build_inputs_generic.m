function build_inputs_generic(particle_dir, rootdir, pattern)
%% build_inputs_generic
% Generic stw version of STOPGAP's build_inputs: works for any particle_dir +
% glob pattern, treating every particle as belonging to one virtual tomogram
% (matching the FM_easy/T3SS build_inputs variants' pattern, not T4P's
% per-tomogram-regex one -- appropriate here since stw has no real per-tomogram
% grouping info for an arbitrary user's particle set).

files = dir(fullfile(particle_dir, pattern));
names = sort({files.name});
n = numel(names);
if n == 0
    error('ACHTUNG!!! No files matching %s found in %s', pattern, particle_dir);
end
fprintf('[build_inputs_generic] found %d particles in %s\n', n, particle_dir);

fn = sg_get_motl_fields();
motl = struct();
for i = 1:size(fn,1)
    if strcmp(fn{i,2},'str')
        motl.(fn{i,1}) = repmat({''},n,1);
    else
        motl.(fn{i,1}) = zeros(n,1);
    end
end

sub_dir   = fullfile(rootdir, 'subtomograms');
lists_dir = fullfile(rootdir, 'lists');
meta_dir  = fullfile(rootdir, 'meta');
for d = {sub_dir, lists_dir, meta_dir}
    if ~exist(d{1},'dir'), mkdir(d{1}); end
end

for i = 1:n
    motl.tomo_num(i)    = 1;
    motl.object(i)      = i;
    motl.subtomo_num(i) = i;
    motl.motl_idx(i)    = i;
    motl.score(i)       = 1;
    motl.class(i)       = 1;

    src = fullfile(particle_dir, names{i});
    dst = fullfile(sub_dir, sprintf('subtomo_%d.mrc', i));
    if ~exist(dst, 'file')
        ret = system(sprintf('ln -s "%s" "%s"', src, dst));
        if ret ~= 0
            error('ACHTUNG!!! Failed to symlink: %s -> %s', src, dst);
        end
    end
end

hs = repmat({'A'}, n, 1);
hs(mod((1:n)', 2) == 0) = {'B'};
motl.halfset = hs;
motl.class   = int32(motl.class);

sg_motl_write2(fullfile(lists_dir, 'allmotl_1.star'), motl);
fprintf('[build_inputs_generic] wrote %d particles to lists/allmotl_1.star\n', n);

writematrix(1, fullfile(meta_dir, 'tomo_nums.csv'));
fprintf('[build_inputs_generic] wrote meta/tomo_nums.csv (tomo_num=1)\n');
end
