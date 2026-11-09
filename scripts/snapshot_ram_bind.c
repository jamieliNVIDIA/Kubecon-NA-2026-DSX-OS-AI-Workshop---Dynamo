/* Narrow test helper: clone one approved tmpfs subtree into the agent's private
 * mount namespace. Same open_tree/mount_setattr/move_mount sequence used by
 * Snapshot 0.1.0's ns-bind-mount. Enter the source namespace only to clone;
 * return to the agent namespace before attaching. No host-mount writes. */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/magic.h>
#include <linux/mount.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <unistd.h>

static int safe_source(const char *path) {
    const char *prefix = "/proc/1/root/var/lib/kubelet/pods/";
    size_t n = strlen(prefix);
    if (strncmp(path, prefix, n) != 0 || strlen(path + n) < 36) return 0;
    for (size_t i = 0; i < 36; i++) {
        char c = path[n + i];
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (c != '-') return 0;
        } else if (!strchr("0123456789abcdef", c)) return 0;
    }
    const char *suffix = path + n + 36;
    return strcmp(suffix, "/volumes/kubernetes.io~empty-dir/staging/artifact") == 0 ||
           strcmp(suffix, "/volumes/kubernetes.io~empty-dir/staging/probe") == 0;
}

static int safe_target(const char *path) {
    if (strcmp(path, "/checkpoints/artifacts/dd493b26-b781-4415-b1f2-090551ae983a") == 0) return 1;
    const char *prefix = "/tmp/snapshot-ram-probe-";
    size_t n = strlen(prefix);
    if (strncmp(path, prefix, n) != 0 || !path[n]) return 0;
    for (const char *p = path + n; *p; p++)
        if (!(isalnum((unsigned char)*p) || *p == '-')) return 0;
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 3 || !safe_source(argv[1]) || !safe_target(argv[2])) {
        fprintf(stderr, "Only this test's helper tmpfs and checkpoint/probe target are allowed\n");
        return 2;
    }
    struct stat current_ns, host_ns, target;
    struct statfs source_fs;
    if (stat("/proc/self/ns/mnt", &current_ns) || stat("/proc/1/ns/mnt", &host_ns) ||
        lstat(argv[2], &target) || statfs(argv[1], &source_fs)) {
        perror("validate mount context"); return 1;
    }
    if (current_ns.st_ino == host_ns.st_ino || !S_ISDIR(target.st_mode) ||
        source_fs.f_type != TMPFS_MAGIC) {
        fprintf(stderr, "Require a separate mount namespace, plain destination directory and tmpfs source\n");
        return 2;
    }
    /* Linux rejects cloning a mount reached through another namespace's proc
     * root. Clone with a root dirfd while in its owning namespace, then attach
     * only after returning to the original private agent namespace. */
    int agent_ns = open("/proc/self/ns/mnt", O_RDONLY | O_CLOEXEC);
    int host_ns_fd = open("/proc/1/ns/mnt", O_RDONLY | O_CLOEXEC);
    int host_root = open("/proc/1/root", O_PATH | O_DIRECTORY | O_CLOEXEC);
    if (agent_ns < 0 || host_ns_fd < 0 || host_root < 0) {
        perror("open namespace handles"); return 1;
    }
    if (setns(host_ns_fd, CLONE_NEWNS)) { perror("enter source namespace to clone"); return 1; }
    int tree = syscall(SYS_open_tree, host_root, argv[1] + strlen("/proc/1/root/"),
                       OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC);
    int clone_errno = errno;
    if (setns(agent_ns, CLONE_NEWNS)) { perror("return to private agent namespace"); return 1; }
    close(agent_ns); close(host_ns_fd); close(host_root);
    errno = clone_errno;
    if (tree < 0) { perror("open_tree clone"); return 1; }
    struct mount_attr attrs = {.attr_set = MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID |
                                           MOUNT_ATTR_NODEV | MOUNT_ATTR_NOEXEC};
    if (syscall(SYS_mount_setattr, tree, "", AT_EMPTY_PATH, &attrs, sizeof(attrs))) {
        perror("mount_setattr readonly"); close(tree); return 1;
    }
    if (syscall(SYS_move_mount, tree, "", AT_FDCWD, argv[2], MOVE_MOUNT_F_EMPTY_PATH)) {
        perror("move_mount into private namespace"); close(tree); return 1;
    }
    close(tree);
    printf("Attached read-only tmpfs clone at %s\n", argv[2]);
    return 0;
}
