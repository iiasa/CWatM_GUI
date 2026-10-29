/**
 * Converts the dispatched job's own absolute output path (read from its
 * `@@CWATM_GUI:OUTPUT_DIR:<path>@@` log marker - see jobs.ts's buildCommand
 * and jobStatus.ts's parsing of it) into the project-relative path
 * listFiles/getFileDownloadUrl expect.
 *
 * /mnt/wdrv is the project's own FUSE-mounted root - i.e. `/mnt/wdrv/<rest>`
 * corresponds to project path `<projectSlug>/<rest>`. Confirmed live twice:
 * job 15561's build log (2026-10-29) showed the Accelerator's own
 * `UploadWdrvFilesCreatedByJobGid` upload step scanning exactly this mount,
 * and job 15631 (2026-10-29, full successful run) had its 75 output files
 * registered at exactly the paths this function predicts (verified both in
 * that job's own log and live in the app's Output files listing).
 */
export function wdrvPathToProjectPath(projectSlug: string, absoluteWdrvPath: string): string {
  const relative = absoluteWdrvPath.replace(/^\/mnt\/wdrv\/?/, "");
  return relative ? `${projectSlug}/${relative}` : projectSlug;
}
