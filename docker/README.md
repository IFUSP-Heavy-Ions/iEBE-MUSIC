## The container

`Dockerfile` builds the whole chain from pinned sources: the base image by
digest, system packages from a frozen OS snapshot, Python packages by version,
the framework by commit, and through it every physics code by commit
(`codes/get_code_packages.sh`).

    docker build -t iebe-music:full .                                    # every backend
    docker build --build-arg WITH_OPTIONAL_CODES=0 -t iebe-music:slim .   # TRENTo + hydro + iSS + decays

The framework pin cannot name the commit that contains it, so it always points
at an earlier commit: to ship a change, commit and push it, then bump the SHA
in the following commit. `scripts/check_docker_pin.sh` checks the pin before a
push.

For Singularity/Apptainer (what OSG jobs run):

    docker save iebe-music:slim | gzip > iebe-music_slim.tar.gz
    singularity build iebe-music_slim_<framework-sha>_<md5prefix8>.sif docker-archive://iebe-music_slim.tar.gz

Give every published image a new name; never overwrite one
(`docs/osg_operations.md`). `docs/chain.md` has the full build, publish and
validation procedure. `Dockerfile_ubuntu` is an Ubuntu-based variant of the
same build.
