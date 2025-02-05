import hashlib
import os
import tlsh
import ssdeep
from quarantineThreats import Quarantine

class Scanner:
    def __init__(self, sha256_signatures, md5_signatures, sha1_signatures, tlsh_signatures, rootPath, yara_rules, virusshare_md5_signatures,ssdeep_signatures):
        self.__sha256_signatures = sha256_signatures
        self.__md5_signatures = md5_signatures
        self.__sha1_signatures = sha1_signatures
        self.__tlsh_signatures = tlsh_signatures
        self.virusshare_md5_signatures_data = virusshare_md5_signatures
        self.ssdeep_signatures_data = ssdeep_signatures
        self.__rootPath = rootPath
        self.yara_rules = yara_rules
        self.quarantineData = {
            'configFileName': 'quar_info',
            'configFilePath': os.path.join(self.__rootPath, 'config'),
            'defaults': {}
        }
        print("-----Scanner Initialized-----")
        self.quar = Quarantine(self.quarantineData)

        # Read excluded rule names from the file
        excluded_rules_path = os.path.join(self.__rootPath, 'excluded', 'excluded_rules.txt')
        with open(excluded_rules_path, "r") as file:
            self.excluded_rules = file.read()

    def getSHA1Hash(self, path):
        try:
            with open(path, 'rb') as f:
                bytes = f.read()
                # Check if the file is empty
                if not bytes:
                    print("File is empty. Skipping hash calculation.")
                    return None  # Return None for an empty file

                hash = hashlib.sha1(bytes).hexdigest()
                return hash
        except (PermissionError, OSError):
            print("Permission Error")
            return "XYLENT_PERMISSION_ERROR"

    def getFileHash(self, path):
        try:
            with open(path, 'rb') as f:
                bytes = f.read()

                # Check if the file is empty
                if not bytes:
                    print("File is empty. Skipping hash calculation.")
                    return None  # Return None for an empty file

                hash = hashlib.sha256(bytes).hexdigest()
                return hash
        except (PermissionError, OSError):
            print("Permission Error")
            return "XYLENT_PERMISSION_ERROR"
    def getSSDEEPhash(self, path):
        try:
            with open(path, 'rb') as f:
                file_content = f.read()

            # Check if the file is empty
            if not file_content:
                print("File is empty. Skipping SSDEEP hash calculation.")
                return None

            ssdeep_hash = ssdeep.hash(file_content)
            return ssdeep_hash
        except (PermissionError, OSError):
            print("Permission Error or OS Error. Skipping SSDEEP hash calculation.")
            return None
    def getMD5Hash(self, path):
        try:
            with open(path, 'rb') as f:
                bytes = f.read()

                # Check if the file is empty
                if not bytes:
                    print("File is empty. Skipping hash calculation.")
                    return None  # Return None for an empty file

                hash = hashlib.md5(bytes).hexdigest()
                return hash
        except (PermissionError, OSError):
            print("Permission Error")
            return "XYLENT_PERMISSION_ERROR"

    def calculate_tlsh(self, file_path):
        try:
            with open(file_path, "rb") as file:
                file_data = file.read()
            if file_data:
                tlsh_value = tlsh.hash(file_data)
                return tlsh_value
            else:
                print("File is empty. Skipping TLSH hash calculation.")
                return None
        except (PermissionError, OSError):
            print("Permission Error or OS Error. Skipping TLSH hash calculation.")
            return None

    def getTLSHHash(self, path):
        try:
            with open(path, 'rb') as f:
                file_size = os.path.getsize(path)

                # Check if the file is empty
                if not file_size <= 256:
                    print("File size is 256 bytes or less. Skipping TLSH hash calculation.")
                    return None  # Return None for an empty file

        except (PermissionError, OSError):
            print("Permission Error or OS Error. Skipping TLSH hash calculation.")
            return None

    def verifyExecutableSignature(self, path):
        import subprocess
        import time
        import datetime
        cmd = " " + f'"{path}"'
        command = "(Get-AuthenticodeSignature" + cmd + ").Status"
        process = subprocess.run(['Powershell', '-Command', command], stdout=subprocess.PIPE, encoding='utf-8')
        now = time.time()
        ageInSec = now - os.stat(path).st_mtime
        age = str(datetime.timedelta(seconds=ageInSec))
        if process.stdout.strip() == "HashMismatch" or process.stdout.strip() == "UnknownError":
            return {'score': 80, 'age': age}
        elif process.stdout.strip() == "NotTrusted":
            return {'score': 70, 'age': age}
        elif process.stdout.strip() == "NotSigned":
            return {'score': 30, 'age': age}
        else:
            return {'score': 0, 'age': age}

    def handleArchives(self, path):
        print("Handling Archive!!")
        import shutil
        try:
            archiveExtractPath = "./scanExtracts"
            if archiveExtractPath.split("/")[1] in path:
                print("Skipped to avoid recursion. Depth=1 for scanning archives!")
                return "DONE!"
            else:
                if not os.path.exists(archiveExtractPath):
                    os.mkdir(archiveExtractPath)
                shutil.unpack_archive(path, archiveExtractPath)
                verdicts = self.scanFolders(archiveExtractPath)
                if "[S]" in verdicts or "[Y]" in verdicts:
                    if os.path.exists(archiveExtractPath):
                        print("Malware detected in archive")
                        from notifypy import Notify
                        notification = Notify()
                        # Set notification properties
                        notification.title = "Archive Repaired"
                        notification.message = "Archive with malicious content repaired. Malware removed, Safe content Preserved!"
                        notification.send()
                        self.quar.quarantineFilesInArchive(originalZipPath=path, preserveArchiveContent=True)

        except Exception as e:
            print(e)
        return "DONE!"

    def scanFile(self, path):
        detectionSpace = "SAFE"
        suspScore = 0
        isArchive = False
        try:
            fileExtension = os.path.splitext(path)[1]
            file_size = os.path.getsize(path)
            hashToChk = self.getFileHash(path)
            # Check if the file is empty
            if hashToChk is None:
                print("File is empty. Skipping.")
                return "SKIPPED"
            # Check if the file is empty or size is 4 bytes or less
            if file_size <= 4:
                print("File size is 4 bytes or less. Skipping.")
                return "SKIPPED"

            if hashToChk == "XYLENT_PERMISSION_ERROR":
                return "SKIPPED"

            if fileExtension == ".zip" or fileExtension == ".tar":
                isArchive = True

            if not isArchive and (fileExtension == ".exe" or fileExtension == ".msi"):
                print(path)
                print("Analyzing file signature....")
                exeSigData = self.verifyExecutableSignature(path)
                print(exeSigData)
                suspScore += exeSigData['score']
                if suspScore >= 70:
                    detectionSpace = "Invalid Signature"

            if hashToChk != "" and suspScore < 70:
                # SIGNATURE BASED DETECTION - SHA256
                sha256_match_found = False
                for sha256_hash in self.__sha256_signatures:
                    if sha256_hash == str(hashToChk):
                        print(self.__sha256_signatures[sha256_hash])
                        detectionSpace = "[S]" + self.__sha256_signatures[sha256_hash]
                        sha256_match_found = True
                # Combine hash match checks
                if sha256_match_found:
                    # Set suspScore to 100 or any other value as needed
                    suspScore = 100
            if hashToChk != "" and suspScore < 70:
                # SIGNATURE BASED DETECTION - MD5
                md5_match_found = False
                md5_hash = self.getMD5Hash(path)
                for md5_hash_sig in self.__md5_signatures:
                    if md5_hash == md5_hash_sig:
                        print(self.__md5_signatures[md5_hash_sig])
                        detectionSpace = "[S]" + self.__md5_signatures[md5_hash_sig]
                        md5_match_found = True
                # Combine hash match checks
                if md5_match_found:
                    # Set suspScore to 100 or any other value as needed
                    suspScore = 100
            if hashToChk != "" and suspScore < 70:
                # TLSH BASED DETECTION
                tlsh_match_found = False
                tlsh_hash = self.getTLSHHash(path)
                if tlsh_hash is not None and tlsh_hash != "TNULL":
                    for tlsh_sig in self.__tlsh_signatures:
                        if tlsh_sig != "TNULL":
                            similarity = tlsh.diff(tlsh_hash, tlsh_sig)
                            if similarity <= 0.8:
                                detectionSpace = "[S]" + self.__tlsh_signatures[tlsh_sig]
                                tlsh_match_found = True
                                print(f"Malware detected using TLSH! Signature: {tlsh_sig}, Similarity: {similarity}")
                if tlsh_match_found:
                    suspScore = 100
            if hashToChk != "" and suspScore < 70:
                # SIGNATURE BASED DETECTION - SHA1
                sha1_match_found = False
                sha1_hash = self.getSHA1Hash(path)
                for sha1_hash_sig in self.__sha1_signatures:
                    if sha1_hash == sha1_hash_sig:
                        print(self.__sha1_signatures[sha1_hash_sig])
                        detectionSpace = "[S]" + self.__sha1_signatures[sha1_hash_sig]
                        sha1_match_found = True
            if hashToChk != "" and suspScore < 70:
                # VIRUSSHARE.TXT BASED DETECTION - MD5
                virusshare_match_found = False
                md5_hash = self.getMD5Hash(path)
                if md5_hash in self.virusshare_md5_signatures_data:
                    detectionSpace = "[S] + VirusShare"  # You can add more specific information if available
                    virusshare_match_found = True
                # Combine hash match checks
                if virusshare_match_found:
                    # Set suspScore to 100 or any other value as needed
                    suspScore = 100
                # Combine hash match checks
                if sha1_match_found:
                    # Set suspScore to 100 or any other value as needed
                    suspScore = 100
                # MALSHARE BASED DETECTION - SSDEEP
                if hashToChk != "" and suspScore < 70:
                 ssdeep_match_found = False
                 ssdeep_hash = self.getSSDEEPhash(path)
                 if ssdeep_hash is not None:
                  for ssdeep_sig in self.ssdeep_signatures_data:
                    try:
                     similarity = ssdeep.compare(ssdeep_hash, ssdeep_sig)
                     if similarity != -1 and 0 < similarity <= 0.8:
                          detectionSpace = "[S] + MalShare (SSDEEP)"
                          ssdeep_match_found = True
                          print(f"Malware detected using SSDEEP! Similarity: {similarity}")
                    except Exception as e:
                     pass
                if ssdeep_match_found:
                    # Set suspScore to 100 or any other value as needed
                    suspScore = 100
                # YARA RULES DETECTION
                if not isArchive and suspScore < 70:
                    try:
                        with open(path, 'rb') as f:
                            file_content = f.read()
                        yara_match_found = False
                        for rule_name, compiled_rule in self.yara_rules.items():
                            matches = compiled_rule.match(data=file_content)
                            for match in matches:
                                if match.rule not in self.excluded_rules:
                                    # If any YARA rule matches, consider it as malware
                                    print(f"YARA Rule Match: {rule_name} - {match}")
                                    detectionSpace = "[Y]" + rule_name
                                    yara_match_found = True
                            if yara_match_found:
                                # Set suspScore to 100 or any other value as needed
                                suspScore = 100
                                print(f"Updated suspScore: {suspScore}")
                    except Exception as e:
                        print(f"Error scanning {path} with YARA rules: {e}")
            # Print the verdict
            print(f"Verdict for {path}: {detectionSpace}")

            if not isArchive and suspScore >= 70:
                notif_str = "Xylent is taking action against detected malware " + path
                from notifypy import Notify
                notification = Notify()
                notification.title = "Malware Detected"
                notification.message = notif_str
                notification.send()
                self.quar.quarantine(path, detectionSpace)
            if isArchive:
                self.handleArchives(path)

            return detectionSpace
        except Exception as e:
            print(f"Error scanning {path}: {e}")
            return "SKIPPED"

    def scanFolders(self, location):
        directories = []
        if isinstance(location, list):
            for target in location:
                for (dirpath, dirnames, filenames) in os.walk(target):
                    directories += [os.path.join(dirpath, file) for file in filenames]
        elif isinstance(location, str):
            for (dirpath, dirnames, filenames) in os.walk(location):
                directories += [os.path.join(dirpath, file) for file in filenames]

        scanReport = {}
        for files in directories:
            verdict = self.scanFile(files)
            if verdict:
                print("Verdict is: " + verdict)
                scanReport[files] = verdict
        return scanReport
