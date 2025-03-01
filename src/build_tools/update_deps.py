# -*- coding: utf-8 -*-
# Copyright 2010-2021, Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#     * Neither the name of Google Inc. nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""A helper script to update OSS Mozc build dependencies.

This helper script takes care of updaring build dependencies for legacy GYP
build for OSS Mozc.
"""

import argparse
import dataclasses
import hashlib
import os
import pathlib
import stat
import subprocess
import sys
import time
import zipfile

import requests


ABS_SCRIPT_PATH = pathlib.Path(__file__).absolute()
# src/build_tools/fetch_deps.py -> src/
ABS_MOZC_SRC_DIR = ABS_SCRIPT_PATH.parents[1]
ABS_THIRD_PARTY_DIR = ABS_MOZC_SRC_DIR.joinpath('third_party')
CACHE_DIR = ABS_MOZC_SRC_DIR.joinpath('third_party_cache')
TIMEOUT = 600


@dataclasses.dataclass
class ArchiveInfo:
  """Third party archive file to be used to build Mozc binaries.

  Attributes:
    url: URL of the archive.
    size: File size of the archive.
    sha256: SHA-256 of the archive.
  """
  url: str
  size: int
  sha256: str

  @property
  def filename(self) -> str:
    """The filename of the archive."""
    return self.url.split('/')[-1]

  def __hash__(self):
    return hash(self.sha256)


QT6 = ArchiveInfo(
    url='https://download.qt.io/archive/qt/6.8/6.8.0/submodules/qtbase-everywhere-src-6.8.0.tar.xz',
    size=49819628,
    sha256='1bad481710aa27f872de6c9f72651f89a6107f0077003d0ebfcc9fd15cba3c75',
)

NINJA_MAC = ArchiveInfo(
    url='https://github.com/ninja-build/ninja/releases/download/v1.11.0/ninja-mac.zip',
    size=277298,
    sha256='21915277db59756bfc61f6f281c1f5e3897760b63776fd3d360f77dd7364137f',
)

NINJA_WIN = ArchiveInfo(
    url='https://github.com/ninja-build/ninja/releases/download/v1.11.0/ninja-win.zip',
    size=285411,
    sha256='d0ee3da143211aa447e750085876c9b9d7bcdd637ab5b2c5b41349c617f22f3b',
)


def get_sha256(path: pathlib.Path) -> str:
  """Returns SHA-256 hash digest of the specified file.

  Args:
    path: Local path the file to calculate SHA-256 about.
  Returns:
    SHA-256 hash digestd of the specified file.
  """
  with open(path, 'rb') as f:
    try:
      # hashlib.file_digest is available in Python 3.11+
      return hashlib.file_digest(f, 'sha256').hexdigest()
    except AttributeError:
      # Fallback to f.read().
      h = hashlib.sha256()
      h.update(f.read())
      return h.hexdigest()


def download(archive: ArchiveInfo, dryrun: bool = False) -> None:
  """Download the specified file.

  Args:
    archive: ArchiveInfo to be downloaded.
    dryrun: True if this is a dry-run.

  Raises:
    RuntimeError: When the downloaded file looks to be corrupted.
  """

  path = CACHE_DIR.joinpath(archive.filename)
  if path.exists():
    if (
        path.stat().st_size == archive.size
        and get_sha256(path) == archive.sha256
    ):
      # Cache hit.
      return
    else:
      if dryrun:
        print(f'dryrun: Verification failed. removing {path}')
      else:
        path.unlink()

  if dryrun:
    print(f'Download {archive.url} to {path}')
    return

  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  saved = 0
  hasher = hashlib.sha256()
  with requests.get(archive.url, stream=True, timeout=TIMEOUT) as r:
    with ProgressPrinter() as printer:
      with open(path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
          f.write(chunk)
          hasher.update(chunk)
          saved += len(chunk)
          printer.print_line(f'{archive.filename}: {saved}/{archive.size}')
  if saved != archive.size:
    raise RuntimeError(
        f'{archive.filename} size mismatch.'
        f' expected={archive.size} actual={saved}'
    )
  actual_sha256 = hasher.hexdigest()
  if actual_sha256 != archive.sha256:
    raise RuntimeError(
        f'{archive.filename} sha256 mismatch.'
        f' expected={archive.sha256} actual={actual_sha256}'
    )


class ProgressPrinter:
  """A utility to print progress message with carriage return and trancatoin."""

  def __enter__(self):
    if not sys.stdout.isatty():

      class NoOpImpl:
        """A no-op implementation in case stdout is not attached to concole."""

        def print_line(self, msg: str) -> None:
          """No-op implementation.

          Args:
            msg: Unused.
          """
          del msg  # Unused
          return

      self.cleaner = None
      return NoOpImpl()

    class Impl:
      """A real implementation in case stdout is attached to concole."""
      last_output_time_ns = time.time_ns()

      def print_line(self, msg: str) -> None:
        """Print the given message with carriage return and trancatoin.

        Args:
          msg: Message to be printed.
        """
        colmuns = os.get_terminal_size().columns
        now = time.time_ns()
        if (now - self.last_output_time_ns) < 25000000:
          return
        msg = msg + ' ' * max(colmuns - len(msg), 0)
        msg = msg[0 : (colmuns)] + '\r'
        sys.stdout.write(msg)
        sys.stdout.flush()
        self.last_output_time_ns = now

    class Cleaner:
      def cleanup(self) -> None:
        colmuns = os.get_terminal_size().columns
        sys.stdout.write(' ' * colmuns + '\r')
        sys.stdout.flush()

    self.cleaner = Cleaner()
    return Impl()

  def __exit__(self, *exc):
    if self.cleaner:
      self.cleaner.cleanup()


def extract_ninja(dryrun: bool = False) -> None:
  """Extract ninja-win archive.

  Args:
    dryrun: True if this is a dry-run.
  """
  dest = ABS_THIRD_PARTY_DIR.joinpath('ninja').absolute()
  if is_mac():
    archive = NINJA_MAC
    exe = 'ninja'
  elif is_windows():
    archive = NINJA_WIN
    exe = 'ninja.exe'
  else:
    return
  src = CACHE_DIR.joinpath(archive.filename)

  if dryrun:
    if dest.exists():
      print(f"dryrun: shutil.rmtree(r'{dest}')")
    print(f'dryrun: Extracting {exe} from {src} into {dest}')
    return

  with zipfile.ZipFile(src) as z:
    z.extract(exe, path=dest)

  if is_mac():
    ninja = dest.joinpath(exe)
    ninja.chmod(ninja.stat().st_mode | stat.S_IXUSR)


def is_windows() -> bool:
  """Returns true if the platform is Windows."""
  return os.name == 'nt'


def is_mac() -> bool:
  """Returns true if the platform is Mac."""
  return os.name == 'posix' and os.uname()[0] == 'Darwin'


def update_submodules(dryrun: bool = False) -> None:
  """Run 'git submodule update --init --recursive'.

  Args:
    dryrun: true to perform dryrun.
  """
  command = ' '.join(['git', 'submodule', 'update', '--init', '--recursive'])
  if dryrun:
    print(f'dryrun: subprocess.run({command}, shell=True, check=True)')
  else:
    subprocess.run(command, shell=True, check=True)


def exec_command(args: list[str], cwd: os.PathLike[str]) -> None:
  """Runs the given command then returns the output.

  Args:
    args: The command to be executed.
    cwd: The working directory to execute the command.

  Raises:
    ChildProcessError: When the given command cannot be executed.
  """
  process = subprocess.Popen(args, stdout=subprocess.PIPE, shell=False, cwd=cwd)
  _, _ = process.communicate()
  exitcode = process.wait()
  if exitcode != 0:
    raise ChildProcessError(f'Failed to execute {args}')


def restore_dotnet_tools(dryrun: bool = False) -> None:
  """Run 'dotnet tool restore'.

  Args:
    dryrun: true to perform dryrun.
  """
  args = ['dotnet', 'tool', 'restore']
  if dryrun:
    print(f'dryrun: exec_command({args}, cwd={ABS_MOZC_SRC_DIR})')
  else:
    exec_command(args, cwd=ABS_MOZC_SRC_DIR)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--dryrun', action='store_true', default=False)
  parser.add_argument('--noninja', action='store_true', default=False)
  parser.add_argument('--noqt', action='store_true', default=False)
  parser.add_argument('--nowix', action='store_true', default=False)
  parser.add_argument('--nosubmodules', action='store_true', default=False)
  parser.add_argument('--cache_only', action='store_true', default=False)

  args = parser.parse_args()

  archives = []
  if (not args.noqt) and (is_windows() or is_mac()):
    archives.append(QT6)
  if (not args.noninja):
    if is_mac():
      archives.append(NINJA_MAC)
    elif is_windows():
      archives.append(NINJA_WIN)

  for archive in archives:
    download(archive, args.dryrun)

  if args.cache_only:
    return

  if (not args.nowix) and is_windows():
    restore_dotnet_tools(args.dryrun)

  if (NINJA_WIN in archives) or (NINJA_MAC in archives):
    extract_ninja(args.dryrun)

  if not args.nosubmodules:
    update_submodules(args.dryrun)


if __name__ == '__main__':
  main()
