# Phase B0 validation-set reference graph labels

Audit source: docs/eval/phaseB0_audit_validation.jsonl
Split: validation (60 awoc traces, seed 2)
Mode: strict
Labeling pass: one-shot

## Summary

### FP audit (precision)

| edge kind      | TP | FP | ambig | decidable | precision |
| -------------- | -: | -: | ----: | --------: | --------: |
| file_reread    | 123 | 10 | 0 | 133 | 0.925 |
| exact_quote    | 29 | 94 | 0 | 123 | 0.236 |
| file_discovery | 78 | 4 | 0 | 82 | 0.951 |
| **overall**    | **230** | **108** | **0** | **338** | **0.680** |

### FN audit (recall lower bound)

| missed | correct_empty | ambig | decidable | miss rate on zero-incoming |
| -----: | ------------: | ----: | --------: | -------------------------: |
| 6 | 174 | 0 | 180 | 0.033 |

## Per-record labels

### FP candidates

| # | trace | edge_kind | src_seg | tgt_seg | label | note |
| -: | ----- | --------- | ------- | ------- | ----- | ---- |
| 1 | 91404059 | file_reread | 6bf7d553c9b6db4c | f81932267dcb9054 | TP | tr content confirmed via file/content analysis |
| 2 | 91404059 | file_reread | af8aa09f65faf267 | c2b2ba620d3c1e22 | TP | tr content confirmed via file/content analysis |
| 3 | 91404059 | file_reread | 540a1b10e8edfaf7 | f81932267dcb9054 | TP | src_file matches tgt_file |
| 4 | 91404059 | file_reread | 7f9d41ecc681233b | f851b718845963fc | TP | src_file matches tgt_file |
| 5 | 91404059 | file_reread | a19bfd717bfe6340 | f851b718845963fc | TP | tr content confirmed via file/content analysis |
| 6 | 91404059 | file_reread | 4e84b68111f72e0b | f851b718845963fc | TP | tr content confirmed via file/content analysis |
| 7 | 2693f60b | file_reread | b42e8b42f1096227 | 14a37791c1a822b8 | TP | src_file matches tgt_file |
| 8 | 2693f60b | file_reread | 63eb6de10decf39b | d00016653aafe4fb | TP | src_file matches tgt_file |
| 9 | 2c58149e | file_reread | 14e3bda1488ae8cb | 7fd499e28ecb9546 | TP | tr content confirmed via file/content analysis |
| 10 | 2c58149e | file_reread | 37a2fde7fc907f3c | df8dab72874c892c | TP | src_file matches tgt_file |
| 11 | 1b45e261 | file_reread | b94fbe7eda5353e7 | 1f8ec30c0fdb571f | TP | tr content confirmed via file/content analysis |
| 12 | 1b45e261 | file_reread | 5fe4badab379e767 | fc81c4e115cca500 | TP | tr content confirmed via file/content analysis |
| 13 | 1b45e261 | file_reread | b25b5bd3c7d823b4 | 1f8ec30c0fdb571f | TP | src_file matches tgt_file |
| 14 | 31a50fe9 | file_reread | 0d62b54e56af29ef | c84b7419a1d5e9ee | FP | empty grep result, no path evidence |
| 15 | 31a50fe9 | file_reread | 136a26697260b2cd | a791a297bcc72f1c | TP | tr content confirmed via file/content analysis |
| 16 | 31a50fe9 | file_reread | 5541279ffc153e74 | 9e3015f13ae4c9b0 | TP | tr content confirmed via file/content analysis |
| 17 | 6c89caa7 | file_reread | 92fdfbc3d7cb4e26 | 1fe20c41750a5cf8 | TP | tr content confirmed via file/content analysis |
| 18 | 6c89caa7 | file_reread | 6c98395dfc54f3bf | 38163e88c82d065a | TP | src_file matches tgt_file |
| 19 | 8e690c72 | file_reread | 69b7fc46bc237698 | 2b2446455cc6f0f1 | TP | src_file matches tgt_file |
| 20 | 8e690c72 | file_reread | 73c5620d780929a2 | 2b2446455cc6f0f1 | TP | tr content confirmed via file/content analysis |
| 21 | 8e690c72 | file_reread | 6e2ab31fccf7e8de | 279950b400deba00 | TP | src_file matches tgt_file |
| 22 | fb40f1b7 | file_reread | 780e78f32e26366f | c8f9a3d1bf830ae9 | TP | src_file matches tgt_file |
| 23 | fb40f1b7 | file_reread | e479d0a5838e1e4c | a52de588f79d87e7 | TP | tr content confirmed via file/content analysis |
| 24 | fb40f1b7 | file_reread | e1b2d365c0f72567 | 6b66a31906457ad8 | FP | empty grep result, no path evidence |
| 25 | c1ee68aa | file_reread | 7e421504d1ef1e55 | cc62268dff5d346c | TP | src_file matches tgt_file |
| 26 | c1ee68aa | file_reread | 6b02865e24ad98d1 | cc62268dff5d346c | TP | tr content confirmed via file/content analysis |
| 27 | 2c58149e | file_reread | 2f9c236a7364b0eb | 3fb0d94f8251aa87 | TP | tr content confirmed via file/content analysis |
| 28 | 2c58149e | file_reread | e2e2ce0d47721e07 | ffe59410837c28cd | TP | src_file matches tgt_file |
| 29 | f764d6fc | file_reread | 98e9230c812676cd | df7735b4eb65aaff | TP | tr content confirmed via file/content analysis |
| 30 | f764d6fc | file_reread | c80c523b3d437e69 | 0e6948c515160f0f | TP | src_file matches tgt_file |
| 31 | b724a2e8 | file_reread | 1b2c3eaabf29a7cb | ded256aea9aff170 | TP | src_file matches tgt_file |
| 32 | b724a2e8 | file_reread | 9d2705f976beac68 | 041f4967646c5ecb | TP | tr content confirmed via file/content analysis |
| 33 | f8c8b590 | file_reread | 9eec5440a4b84e3b | ece92a0f93680e9a | TP | src_file matches tgt_file |
| 34 | f8c8b590 | file_reread | 67ba4f02873a0747 | 1fc5d3e768aedc06 | TP | src_file matches tgt_file |
| 35 | 6e4a7b52 | file_reread | e06e803c8f01de86 | c16dc550eb9327ff | TP | src_file matches tgt_file |
| 36 | 6e4a7b52 | file_reread | 92f83faeab45163d | c16dc550eb9327ff | TP | tr content confirmed via file/content analysis |
| 37 | 6e4a7b52 | file_reread | 33e077b63dfb9e38 | af56ddaa2450948d | TP | tr content confirmed via file/content analysis |
| 38 | c1ee68aa | file_reread | e048ea644364c949 | c733d9b2469a5480 | TP | tr content confirmed via file/content analysis |
| 39 | c1ee68aa | file_reread | 234c53174aa55b49 | c733d9b2469a5480 | TP | tr content confirmed via file/content analysis |
| 40 | c1ee68aa | file_reread | 234c53174aa55b49 | e566249b74f8a0fc | TP | tr content confirmed via file/content analysis |
| 41 | 614b39f0 | file_reread | 3d7085b9316a5133 | 977a58bf4ef13026 | TP | src_file matches tgt_file |
| 42 | 614b39f0 | file_reread | 253de1b5bd371808 | aa4bcf1e84b62754 | TP | src_file matches tgt_file |
| 43 | 614b39f0 | file_reread | 35ce8b11360d8b06 | aa4bcf1e84b62754 | TP | tr content confirmed via file/content analysis |
| 44 | 4f26783b | file_reread | 2f992c1124c276b1 | c44f61011c85d4c8 | TP | tr content confirmed via file/content analysis |
| 45 | 4f26783b | file_reread | 5960162af55a6800 | 680ae8e5da7829e0 | TP | tr content confirmed via file/content analysis |
| 46 | 4e2842a6 | file_reread | 4542e2a1729c81d5 | c0da7d9559a91df3 | TP | tr content confirmed via file/content analysis |
| 47 | 4e2842a6 | file_reread | ffaeb9cd27ae38b4 | ba95b44f52fbb384 | TP | tr content confirmed via file/content analysis |
| 48 | 4e2842a6 | file_reread | bb50cece28c7133f | bea11e028f8d1ce7 | TP | src_file matches tgt_file |
| 49 | 7da7cd16 | file_reread | ca738a8f08c97837 | d4919af311ef0d6c | TP | tr content confirmed via file/content analysis |
| 50 | 7da7cd16 | file_reread | b4ce0a3cb737bb4f | 4f92c6eb1cff751f | TP | src_file matches tgt_file |
| 51 | 7da7cd16 | file_reread | ca7ada4602f0c2e7 | 9a3eb25748c5cdaf | TP | src_file matches tgt_file |
| 52 | f2a74003 | file_reread | eeccbdc07359beff | 81a1b2e1f41ced45 | TP | src_file matches tgt_file |
| 53 | f2a74003 | file_reread | edf448984b8698c3 | 442ef1523c21049a | TP | tr content confirmed via file/content analysis |
| 54 | 31a50fe9 | file_reread | 2b8fdd94147b7808 | 9563ad8f432c94f2 | TP | tr content confirmed via file/content analysis |
| 55 | 31a50fe9 | file_reread | 934d68fee5103922 | b1cf2ac4fd3555c0 | FP | empty grep result, no path evidence |
| 56 | 31a50fe9 | file_reread | 55cd14956a5620c0 | dc5f8fb55258d490 | TP | src_file matches tgt_file |
| 57 | 91404059 | file_reread | cf7210504190c5d1 | 4953e0edcaa653f3 | FP | overflow error, path unverifiable |
| 58 | 91404059 | file_reread | f434aa356ded19b7 | 1275e5dd8b4da658 | TP | src_file matches tgt_file |
| 59 | a54ddd36 | file_reread | ba9c617d4687fb3d | 8d330ac24a7fc308 | TP | tr content confirmed via file/content analysis |
| 60 | a54ddd36 | file_reread | a2e8fcc4f8272366 | 282913bf3ebe4f75 | TP | tr content confirmed via file/content analysis |
| 61 | a54ddd36 | file_reread | f87f2a8042969f65 | 0428ac13670de996 | TP | src_file matches tgt_file |
| 62 | 37e689ad | file_reread | f870e2c8b4367ef3 | 04ada2c089941080 | TP | src_file matches tgt_file |
| 63 | 37e689ad | file_reread | 192d24a5aa77159b | 7cfce48910fddb63 | TP | src_file matches tgt_file |
| 64 | fb40f1b7 | file_reread | 716425436ed7cbdb | ca6d213fc1a3c3b4 | TP | tr content confirmed via file/content analysis |
| 65 | fb40f1b7 | file_reread | 80429f6fa553175a | b26acba0eeb0e940 | TP | src_file matches tgt_file |
| 66 | fb40f1b7 | file_reread | 2a06baa39e010471 | b26acba0eeb0e940 | TP | src_file matches tgt_file |
| 67 | 614b39f0 | file_reread | 214fdeb70d87cc49 | 8413d3019938c169 | TP | tr content confirmed via file/content analysis |
| 68 | 614b39f0 | file_reread | 214fdeb70d87cc49 | 1ea80d69eae2bf1a | TP | tr content confirmed via file/content analysis |
| 69 | 614b39f0 | file_reread | 769ac0b7eb95b85e | 8413d3019938c169 | TP | src_file matches tgt_file |
| 70 | cb9f58bd | file_reread | 1d2e68469c201696 | 0f18bfae8aa49f28 | TP | src_file matches tgt_file |
| 71 | cb9f58bd | file_reread | 73ee96a0a09343b5 | 0f18bfae8aa49f28 | TP | tr content confirmed via file/content analysis |
| 72 | cb9f58bd | file_reread | 4703b17a1478b568 | 1d2e68469c201696 | TP | tr content confirmed via file/content analysis |
| 73 | 0d9c4ae5 | file_reread | 9115bb11c54d165b | 53c9ac909c2536f4 | TP | src_file matches tgt_file |
| 74 | 0d9c4ae5 | file_reread | 196316b6cb3e5d19 | eb6e0c944a00eda1 | TP | src_file matches tgt_file |
| 75 | 7bb6d062 | file_reread | 809076263ad78476 | 86e3af6302123ac5 | TP | src_file matches tgt_file |
| 76 | 7bb6d062 | file_reread | f4ae56da46795be0 | 70bee06fa9c44f34 | TP | src_file matches tgt_file |
| 77 | 87443885 | file_reread | 0469b6b77214073d | c641296eb61966a1 | TP | src_file matches tgt_file |
| 78 | 87443885 | file_reread | 9d90c4c6ccb91613 | ce1ba80f64a114de | TP | src_file matches tgt_file |
| 79 | b724a2e8 | file_reread | 51148958f7d22e8e | f42c3ba54ca57ae6 | TP | tr content confirmed via file/content analysis |
| 80 | b724a2e8 | file_reread | f42c3ba54ca57ae6 | cc5904d974893a46 | TP | src_file matches tgt_file |
| 81 | d834f22c | file_reread | 2ad1747faa1ad09e | 748d057751cf5eae | TP | src_file matches tgt_file |
| 82 | d834f22c | file_reread | 18ebb5055bb4a715 | 154ab5bfbf007a4a | TP | tr content confirmed via file/content analysis |
| 83 | f2a74003 | file_reread | f6c8d42381a351c3 | 3288af730c559a25 | TP | src_file matches tgt_file |
| 84 | f2a74003 | file_reread | a5f1e43645f234cb | 445776811125fd51 | TP | src_file matches tgt_file |
| 85 | d834f22c | file_reread | e38faf82acde7588 | e980a7b1bf7ac7db | TP | tr content confirmed via file/content analysis |
| 86 | d834f22c | file_reread | e104b3c0e397bec2 | 7c32a1c6c393c381 | TP | src_file matches tgt_file |
| 87 | a54ddd36 | file_reread | 82880ccbe152fbc7 | 9e7b1861b863004c | TP | src_file matches tgt_file |
| 88 | a54ddd36 | file_reread | d7284b8fdeb7fe49 | 9e7b1861b863004c | TP | tr content confirmed via file/content analysis |
| 89 | 9898f6d3 | file_reread | 92bfe1924a03bb18 | 6fb95290ea905d6a | TP | tr content confirmed via file/content analysis |
| 90 | 9898f6d3 | file_reread | 4a8e4eac6a03b13a | 2dc0a005d3d1991c | TP | src_file matches tgt_file |
| 91 | 9898f6d3 | file_reread | 4b89929f50d8c9f0 | 6fb95290ea905d6a | TP | src_file matches tgt_file |
| 92 | 37e689ad | file_reread | dfdcde71e98defcd | 1a02623cf06ccebb | FP | empty grep result, no path evidence |
| 93 | 37e689ad | file_reread | 900019af3d445bd7 | 04a044767d669d3a | TP | tr content confirmed via file/content analysis |
| 94 | 37e689ad | file_reread | 57d4725132e0a0dd | e9e6dcb5754ccb93 | TP | tr content confirmed via file/content analysis |
| 95 | 2c58149e | file_reread | 115bbc1f55f3a57b | d46a7484ca26443b | TP | src_file matches tgt_file |
| 96 | 2c58149e | file_reread | d79d84f3dcad66e6 | 071115c70ee8446c | FP | empty grep result, no path evidence |
| 97 | 3998edcf | file_reread | ff1da72700865e9e | fb4824c47b607d9a | TP | src_file matches tgt_file |
| 98 | 3998edcf | file_reread | 9242ddc2a5feb523 | 159d9fc583f711b9 | TP | src_file matches tgt_file |
| 99 | 3998edcf | file_reread | ad81e520b6feb0a0 | 3a93ceb88f8201bc | TP | tr content confirmed via file/content analysis |
| 100 | b724a2e8 | file_reread | 1a775b8ce7a0bf96 | dd12adcb485de7ec | TP | tr content confirmed via file/content analysis |
| 101 | b724a2e8 | file_reread | 35eeb75e187ee8af | 0a5ebc830e0d2fbe | TP | tr content confirmed via file/content analysis |
| 102 | 37e689ad | file_reread | 6d712bbae29c3311 | f2dbe08d14fed771 | TP | tr content confirmed via file/content analysis |
| 103 | 37e689ad | file_reread | e7b51223e5ce844a | f2dbe08d14fed771 | TP | src_file matches tgt_file |
| 104 | 0d9c4ae5 | file_reread | a6096aa163df93f7 | 28ec4684a06f9827 | TP | src_file matches tgt_file |
| 105 | 0d9c4ae5 | file_reread | 18e0928995446c2f | 7708e2741f0b0b95 | TP | src_file matches tgt_file |
| 106 | 51bad63b | file_reread | 232ac80a5568cae8 | 7a433dbecc7c3b32 | FP | tool error source |
| 107 | 51bad63b | file_reread | bca6db00aa597229 | a5e9106cd0a59874 | FP | tool error source |
| 108 | 51bad63b | file_reread | 6e9dd81691fca1ca | d5b6546ed4fdbfa4 | FP | tool error source |
| 109 | 3c0b2ea8 | file_reread | b973dbe2fc1eda7b | c158b998176d855a | TP | src_file matches tgt_file |
| 110 | 3c0b2ea8 | file_reread | 77e7d1013bfd2865 | 753cee9a40c599bb | TP | src_file matches tgt_file |
| 111 | 3c0b2ea8 | file_reread | b973dbe2fc1eda7b | 293a4a6a1f1ba413 | TP | src_file matches tgt_file |
| 112 | e7296f54 | file_reread | aa6d59260cf02ca5 | 74ac8439a01d0d3b | TP | src_file matches tgt_file |
| 113 | e7296f54 | file_reread | 0b90e6ae94f01304 | 669f6ebe86090f4a | TP | tr content confirmed via file/content analysis |
| 114 | 22f0b5a0 | file_reread | 250ad228dd07f15d | af3848c3960b5435 | TP | src_file matches tgt_file |
| 115 | 22f0b5a0 | file_reread | 4abe4e8143d1bf7d | 3489588a56169e68 | TP | tr content confirmed via file/content analysis |
| 116 | 22f0b5a0 | file_reread | 3489588a56169e68 | 1359b5878ba0b0b2 | TP | src_file matches tgt_file |
| 117 | cb9f58bd | file_reread | ec0b05d1de6ff5ba | d46ca0f1b336a1c6 | TP | tr content confirmed via file/content analysis |
| 118 | cb9f58bd | file_reread | 481f402bf41892c4 | 5e9ba7d3d584f988 | TP | src_file matches tgt_file |
| 119 | cb9f58bd | file_reread | 9fe57ca5635bec5b | 88a2df44bbb0d2f4 | TP | tr content confirmed via file/content analysis |
| 120 | 91404059 | file_reread | f050c904d6555b0f | 7eb7596199229e00 | TP | src_file matches tgt_file |
| 121 | 91404059 | file_reread | 6c8f1f8763235421 | b3077df09b00c0ff | TP | src_file matches tgt_file |
| 122 | 91404059 | file_reread | f21bc1697f953ea6 | a60e88a08ed8d182 | TP | tr content confirmed via file/content analysis |
| 123 | 91404059 | file_reread | 8d943d90687d3b53 | a60e88a08ed8d182 | TP | src_file matches tgt_file |
| 124 | 44d85a2d | file_reread | 97e00c6817f85807 | edf0ddd0ac57520b | TP | tr content confirmed via file/content analysis |
| 125 | 44d85a2d | file_reread | 34430302c832666f | 461614f2d7f03de9 | TP | tr content confirmed via file/content analysis |
| 126 | 44d85a2d | file_reread | 899452e8ad60e9d8 | edf0ddd0ac57520b | TP | src_file matches tgt_file |
| 127 | 6d90f64f | file_reread | caabae17bb11c094 | a34b9e51eb571781 | TP | src_file matches tgt_file |
| 128 | 6d90f64f | file_reread | 97bfd3b9769ae798 | 7391237d88bb6988 | TP | src_file matches tgt_file |
| 129 | 6d90f64f | file_reread | 4e1cdb9121861bed | 96964de388e73095 | TP | tr content confirmed via file/content analysis |
| 130 | 767940c1 | file_reread | 19368c86d5296d79 | 2f6290d4298820f9 | TP | src_file matches tgt_file |
| 131 | 767940c1 | file_reread | 71af277017e1bdf6 | 52504faeb3fa042f | FP | tool error source |
| 132 | f2a74003 | file_reread | 9a4327d5621fd534 | b766a63ec2c384ee | TP | tr content confirmed via file/content analysis |
| 133 | f2a74003 | file_reread | d046f17b44fb22c2 | b766a63ec2c384ee | TP | src_file matches tgt_file |
| 134 | 0d9c4ae5 | exact_quote | 8e022e423519e698 | 2995ce785ed88211 | FP | no ≥20-char shared run after path stripping |
| 135 | 91404059 | exact_quote | 9a6973ef20b0d6ce | 9458327c342e02ff | FP | no ≥20-char shared run after path stripping |
| 136 | 91404059 | exact_quote | f924cbe274eb414b | 288e8dd23934622e | FP | heredoc write-through: generic fs import |
| 137 | 91404059 | exact_quote | 6bf7d553c9b6db4c | 9458327c342e02ff | FP | no ≥20-char shared run after path stripping |
| 138 | 91404059 | exact_quote | 05209ee19636bed4 | 5d568dc88c7fb1b3 | TP | ≥20-char match: '*   awoc start    — create tmux ses' |
| 139 | 91404059 | exact_quote | e5718d1f58d9fe8c | 5d568dc88c7fb1b3 | FP | no ≥20-char shared run after path stripping |
| 140 | 91404059 | exact_quote | 951f36812b231902 | 5d568dc88c7fb1b3 | TP | ≥20-char match: '*   awoc start    — create tmux ses' |
| 141 | 2693f60b | exact_quote | 4713a4867bfe5344 | 4e6699947c8aa616 | FP | no ≥20-char shared run after path stripping |
| 142 | 2693f60b | exact_quote | 246d8b1ca5abe899 | 05819c6cf9bc4137 | TP | ≥20-char match: 'pi.on("before_agent_start", async (' |
| 143 | 6e4a7b52 | exact_quote | 6f29eb450e1bf982 | 591bbb27d32b554e | FP | cross-doc boilerplate: README in npm report |
| 144 | 6e4a7b52 | exact_quote | e7756354638be4b6 | 591bbb27d32b554e | FP | no ≥20-char shared run after path stripping |
| 145 | 2c58149e | exact_quote | 283381d5014d1802 | ca80c28d7f7d778b | FP | no ≥20-char shared run after path stripping |
| 146 | 2c58149e | exact_quote | 7e808746f2205e43 | ca80c28d7f7d778b | FP | no ≥20-char shared run after path stripping |
| 147 | 31a50fe9 | exact_quote | 12f40e7cb492aa3d | 4c09a5ba17f9e099 | FP | no ≥20-char shared run after path stripping |
| 148 | 31a50fe9 | exact_quote | 5228b1e902d3668d | bfcf742ac141d4c7 | FP | no ≥20-char shared run after path stripping |
| 149 | 31a50fe9 | exact_quote | 12f40e7cb492aa3d | bfcf742ac141d4c7 | FP | no ≥20-char shared run after path stripping |
| 150 | 6c89caa7 | exact_quote | 1ea34120cf4f66ce | f7a781e90effed68 | FP | no ≥20-char shared run after path stripping |
| 151 | 6c89caa7 | exact_quote | 8e255e8cc321fc62 | f7a781e90effed68 | FP | no ≥20-char shared run after path stripping |
| 152 | 8e690c72 | exact_quote | 5ecf8c91d6edda19 | 8b7a027be13493b3 | TP | ≥20-char match: '@mariozechner/pi-agent-core' |
| 153 | 8e690c72 | exact_quote | f677d96d0a1f7f33 | 8b7a027be13493b3 | FP | no ≥20-char shared run after path stripping |
| 154 | 8e690c72 | exact_quote | 718dc2a109fb831a | 8b7a027be13493b3 | FP | no ≥20-char shared run after path stripping |
| 155 | fb40f1b7 | exact_quote | ee39a5f13e12aba8 | 780e78f32e26366f | FP | no ≥20-char shared run after path stripping |
| 156 | fb40f1b7 | exact_quote | 51731d54daee7ad3 | 07914e37aab8f566 | FP | no ≥20-char shared run after path stripping |
| 157 | fb40f1b7 | exact_quote | ee39a5f13e12aba8 | eeb3560d54a8deb3 | FP | no ≥20-char shared run after path stripping |
| 158 | c1ee68aa | exact_quote | a2ca5b8becddebef | 797770c2fe62380a | FP | no ≥20-char shared run after path stripping |
| 159 | c1ee68aa | exact_quote | a2ca5b8becddebef | e853291153d6f345 | TP | ≥20-char match: 'import { IDENTITY_BLOCK } from ".. ' |
| 160 | 51bad63b | exact_quote | c300b6433366088e | f3437c1dc0ee3fec | FP | no ≥20-char shared run after path stripping |
| 161 | 51bad63b | exact_quote | a7b1296182d47b3e | f3437c1dc0ee3fec | FP | no ≥20-char shared run after path stripping |
| 162 | 51bad63b | exact_quote | b69cbac6edf1a251 | f3437c1dc0ee3fec | FP | no ≥20-char shared run after path stripping |
| 163 | 2c58149e | exact_quote | e4388632beb30e9d | a5c2a80915c8c657 | TP | ≥20-char match: 'loadProfileByName(profileName)' |
| 164 | 2c58149e | exact_quote | ff15d17a72b36724 | a5c2a80915c8c657 | FP | no ≥20-char shared run after path stripping |
| 165 | f764d6fc | exact_quote | eeff193bd30468f7 | 083f4aa3f1ee71af | FP | no ≥20-char shared run after path stripping |
| 166 | f764d6fc | exact_quote | 160d9a1f8b181d9b | 2e643833a40addfc | FP | no ≥20-char shared run after path stripping |
| 167 | b724a2e8 | exact_quote | 3149c4505aa8a8ac | 7e515e955b324fbd | FP | no ≥20-char shared run after path stripping |
| 168 | b724a2e8 | exact_quote | 3149c4505aa8a8ac | c0d80dd56d312fbc | FP | no ≥20-char shared run after path stripping |
| 169 | b60ddfde | exact_quote | 70743dc984aa419b | f832912f298d1091 | FP | no ≥20-char shared run after path stripping |
| 170 | b60ddfde | exact_quote | 00003b025190fbb3 | f832912f298d1091 | FP | no ≥20-char shared run after path stripping |
| 171 | b60ddfde | exact_quote | 7ce90a488448ac7d | f832912f298d1091 | FP | no ≥20-char shared run after path stripping |
| 172 | f8c8b590 | exact_quote | 11c466fb0eac4b41 | f8e68b4073a9c542 | FP | no ≥20-char shared run after path stripping |
| 173 | f8c8b590 | exact_quote | baaba4f1cbee0d7c | f8e68b4073a9c542 | FP | no ≥20-char shared run after path stripping |
| 174 | 6e4a7b52 | exact_quote | 5f38889eb1235b68 | 6f04d8f89b5d00d8 | FP | no ≥20-char shared run after path stripping |
| 175 | 6e4a7b52 | exact_quote | bb26cbc627c4b195 | 6f04d8f89b5d00d8 | TP | ≥20-char match: 'resolution cascade,' |
| 176 | 6e4a7b52 | exact_quote | 0210ef54e1cfc825 | d6b77501992946ec | FP | no ≥20-char shared run after path stripping |
| 177 | c1ee68aa | exact_quote | 234c53174aa55b49 | 73b90adc0886d959 | FP | generic bun:test import boilerplate |
| 178 | 614b39f0 | exact_quote | 1fe12fdcfa4b845a | 946617b31e9953c1 | TP | ≥20-char match: '*   awoc start    — create tmux ses' |
| 179 | 614b39f0 | exact_quote | 1fe12fdcfa4b845a | 6493cad865f0ab6c | FP | no ≥20-char shared run after path stripping |
| 180 | 614b39f0 | exact_quote | a0ede93b8477a582 | 6493cad865f0ab6c | TP | ≥20-char match: '"anthropic/claude-opus-4-6"' |
| 181 | 4f26783b | exact_quote | 554e80dc74980e5e | 523f76841f2f8fad | FP | no ≥20-char shared run after path stripping |
| 182 | 4f26783b | exact_quote | f8ede41322aa7651 | 523f76841f2f8fad | FP | no ≥20-char shared run after path stripping |
| 183 | 4e2842a6 | exact_quote | d1848d232d2a6a65 | 7ab6e02a85eb433b | TP | ≥20-char match: 'record(event: Omit<AuditEvent, "id"' |
| 184 | 4e2842a6 | exact_quote | bb6971366f16c2e1 | 7ab6e02a85eb433b | FP | no ≥20-char shared run after path stripping |
| 185 | 4e2842a6 | exact_quote | f6a20cf3e02f3f12 | 7ab6e02a85eb433b | FP | no ≥20-char shared run after path stripping |
| 186 | 7da7cd16 | exact_quote | d357e719dc4cd76b | 17f28e9c3f1122a3 | FP | no ≥20-char shared run after path stripping |
| 187 | 7da7cd16 | exact_quote | 62e7535fb145afe4 | 25395c076d349475 | FP | no ≥20-char shared run after path stripping |
| 188 | 7da7cd16 | exact_quote | c9f020989b0f92f3 | 25395c076d349475 | TP | ≥20-char match: 'PanCode is pre-1.0.' |
| 189 | f2a74003 | exact_quote | bf558bc1d3b29f13 | 41e5bf23d3f6230f | FP | no ≥20-char shared run after path stripping |
| 190 | f2a74003 | exact_quote | dbffda4867406699 | 41e5bf23d3f6230f | FP | no ≥20-char shared run after path stripping |
| 191 | 31a50fe9 | exact_quote | 905262cab3e3eaca | ef4089b06a7549c0 | TP | ≥20-char match: 'NOT here: Pi SDK tool registration ' |
| 192 | 31a50fe9 | exact_quote | 63fb833b3c309698 | c116c4c28d80e362 | TP | ≥20-char match: 'NOT here: Pi SDK integration, actua' |
| 193 | 31a50fe9 | exact_quote | b66fee9b077daefb | c25f96c41d09fab5 | FP | no ≥20-char shared run after path stripping |
| 194 | 91404059 | exact_quote | 8c16103b8415b220 | cd55c1136c4a0ee1 | FP | no ≥20-char shared run after path stripping |
| 195 | 91404059 | exact_quote | cf89eda1bca83d92 | cd55c1136c4a0ee1 | FP | no ≥20-char shared run after path stripping |
| 196 | a54ddd36 | exact_quote | 014d912a6d24ce49 | 9205476b74b61162 | FP | no ≥20-char shared run after path stripping |
| 197 | a54ddd36 | exact_quote | e9582cf55473956d | fa95fe8877cd5f4d | FP | no ≥20-char shared run after path stripping |
| 198 | a54ddd36 | exact_quote | 78634cc0c9f4f4f4 | 920175ba60a40637 | FP | no ≥20-char shared run after path stripping |
| 199 | 37e689ad | exact_quote | 84cfa1e37f2a86ca | 15914bb34343d594 | FP | no ≥20-char shared run after path stripping |
| 200 | fb40f1b7 | exact_quote | 832791158b8296f6 | 87101fdfc86c7f89 | FP | no ≥20-char shared run after path stripping |
| 201 | 61e2fc56 | exact_quote | 924ce8dbf98e76a4 | 7ad041ba43119662 | FP | no ≥20-char shared run after path stripping |
| 202 | 61e2fc56 | exact_quote | fcd66f790504b1f5 | 7ad041ba43119662 | FP | no ≥20-char shared run after path stripping |
| 203 | 61e2fc56 | exact_quote | 2aae6cc64ab609c6 | 7ad041ba43119662 | FP | no ≥20-char shared run after path stripping |
| 204 | cb9f58bd | exact_quote | 4703b17a1478b568 | e64e2395eed20856 | TP | ≥20-char match: 'import { AuthStorage, ModelRegistry' |
| 205 | cb9f58bd | exact_quote | 31878555fe6b5e6b | e64e2395eed20856 | TP | ≥20-char match: 'import { AuthStorage, ModelRegistry' |
| 206 | 0d9c4ae5 | exact_quote | f61bdb3832b9d3cf | 82449abca5203875 | FP | no ≥20-char shared run after path stripping |
| 207 | 0d9c4ae5 | exact_quote | 841aed565645ab32 | 3624af15f117e172 | FP | no ≥20-char shared run after path stripping |
| 208 | 7bb6d062 | exact_quote | 00dec68254262c79 | 64a47e8de1c93f5a | TP | ≥20-char match: 'test("interception event has correc' |
| 209 | 7bb6d062 | exact_quote | 30bb8e63a0d15472 | 5a306aec798df42f | FP | heredoc write-through: generic fs import |
| 210 | 87443885 | exact_quote | f3ac68bfc6381d89 | 31f4e0e782efe5a8 | FP | no ≥20-char shared run after path stripping |
| 211 | 87443885 | exact_quote | 3bfb2aa037751bb5 | 87a441eb971ddf32 | FP | no ≥20-char shared run after path stripping |
| 212 | b724a2e8 | exact_quote | f1d5d06a587f77dd | b08f266167c87cf1 | FP | no ≥20-char shared run after path stripping |
| 213 | b724a2e8 | exact_quote | fcaa16764278e2b7 | ba280343f4b54e93 | FP | no ≥20-char shared run after path stripping |
| 214 | d834f22c | exact_quote | 7cc8303bd3dd8467 | cb24b15959fabc8a | FP | no ≥20-char shared run after path stripping |
| 215 | d834f22c | exact_quote | 279a0fc6ac402289 | 9de2646073a98aa2 | FP | no ≥20-char shared run after path stripping |
| 216 | f2a74003 | exact_quote | 5ed51a1850397e5a | a3b1c16c911b5e4a | FP | no ≥20-char shared run after path stripping |
| 217 | f2a74003 | exact_quote | 452c46760841ca2b | 90848bc65d7d4dd2 | FP | no ≥20-char shared run after path stripping |
| 218 | d834f22c | exact_quote | 4d5cbd31699f8904 | 942315ed82cae9e1 | FP | no ≥20-char shared run after path stripping |
| 219 | d834f22c | exact_quote | a131656cab7a6ec4 | 942315ed82cae9e1 | FP | no ≥20-char shared run after path stripping |
| 220 | a54ddd36 | exact_quote | 4a5c696c6f11d481 | 55f195410589451f | FP | no ≥20-char shared run after path stripping |
| 221 | a54ddd36 | exact_quote | 1c331d5878618a5d | 55f195410589451f | FP | no ≥20-char shared run after path stripping |
| 222 | 9898f6d3 | exact_quote | 92bfe1924a03bb18 | 8bc76bf810e0e54e | FP | no ≥20-char shared run after path stripping |
| 223 | 9898f6d3 | exact_quote | 92bfe1924a03bb18 | 9b087a660ff45809 | FP | no ≥20-char shared run after path stripping |
| 224 | 9898f6d3 | exact_quote | 85d00be3f84187b6 | 563648182004da1a | TP | ≥20-char match: 'buildScopeViolationEvent' |
| 225 | 76086107 | exact_quote | a4b6c634b75fd34a | 4a93175838d31944 | FP | no ≥20-char shared run after path stripping |
| 226 | 76086107 | exact_quote | 965d471f77ef36ce | 4a93175838d31944 | FP | no ≥20-char shared run after path stripping |
| 227 | 76086107 | exact_quote | b767814aca0c6360 | 4a93175838d31944 | FP | cross-doc boilerplate: project title in feature report |
| 228 | 37e689ad | exact_quote | 104813f667382711 | c6a5f46e57f25529 | FP | no ≥20-char shared run after path stripping |
| 229 | 37e689ad | exact_quote | 4afe8439f2f64dcb | deb94d523dd5d58a | TP | ≥20-char match: '*   awoc start    — create tmux ses' |
| 230 | 37e689ad | exact_quote | 4afe8439f2f64dcb | c6a5f46e57f25529 | TP | ≥20-char match: '*   awoc start    — create tmux ses' |
| 231 | 2c58149e | exact_quote | 219a5904b7df9b12 | 99dd72d24d95b8ef | TP | ≥20-char match: 'Dispatch pipeline observer' |
| 232 | 2c58149e | exact_quote | 3df7f1f6ecfb4e82 | 99dd72d24d95b8ef | FP | no ≥20-char shared run after path stripping |
| 233 | b724a2e8 | exact_quote | 05cd2f13b4e32994 | 8f15a72f8748741d | TP | ≥20-char match: 'import { existsSync, readFileSync }' |
| 234 | b724a2e8 | exact_quote | b654cfd1b50db52f | 51575cbd8c62c240 | TP | ≥20-char match: 'Commands: /status /tasks /agents /r' |
| 235 | 0d9c4ae5 | exact_quote | 41f206fa4fdf33e2 | 3c6b75f87f8440a1 | FP | no ≥20-char shared run after path stripping |
| 236 | 0d9c4ae5 | exact_quote | 3b230ed5c1835140 | f3e9225b25be1fc0 | TP | ≥20-char match: 'return runSingleDispatch(params, si' |
| 237 | e7296f54 | exact_quote | 3c33cebecf07b087 | 698527b78038d219 | FP | no ≥20-char shared run after path stripping |
| 238 | 22f0b5a0 | exact_quote | 66babf5cf55af16b | 80e7507d7f89ed7c | FP | no ≥20-char shared run after path stripping |
| 239 | 22f0b5a0 | exact_quote | 4015654b9bbca76b | 3df7a86cb3e2e55a | FP | no ≥20-char shared run after path stripping |
| 240 | cb9f58bd | exact_quote | c7f90e3d1f68a51f | 3049d8973fd0fcdb | FP | no ≥20-char shared run after path stripping |
| 241 | cb9f58bd | exact_quote | 5468e18d68b34ce1 | 49349ecf0d4667f1 | TP | ≥20-char match: 'export async function loadProviderO' |
| 242 | cb9f58bd | exact_quote | c7f90e3d1f68a51f | 5dc876f3127e6845 | TP | ≥20-char match: '* - Git-backed tracking (git add af' |
| 243 | 91404059 | exact_quote | 95dfec4d6bb53f8d | f9c240c5cf486fdf | FP | no ≥20-char shared run after path stripping |
| 244 | 91404059 | exact_quote | 817c037bc2fa92d0 | f9c240c5cf486fdf | TP | ≥20-char match: 'checkForNewVersion()' |
| 245 | 91404059 | exact_quote | 5fb00d82bd73baba | b3b76d58eab5d910 | FP | no ≥20-char shared run after path stripping |
| 246 | 91404059 | exact_quote | a269d9b4fd59d07e | b3b76d58eab5d910 | FP | no ≥20-char shared run after path stripping |
| 247 | 44d85a2d | exact_quote | 1182aa33ae78e3a2 | ad85873a9da2c2eb | TP | ≥20-char match: 'import { basename, join } from "nod' |
| 248 | 44d85a2d | exact_quote | 9e394305157ddd29 | f360138ee013899e | FP | no ≥20-char shared run after path stripping |
| 249 | 44d85a2d | exact_quote | 1182aa33ae78e3a2 | f360138ee013899e | FP | no ≥20-char shared run after path stripping |
| 250 | 6d90f64f | exact_quote | 27a06c4e9719aafe | 5802d59e5bf227b7 | TP | ≥20-char match: 'import { Box, Text } from "@marioze' |
| 251 | 6d90f64f | exact_quote | 3e21b09e35e6233b | 9755c0c39be59a31 | FP | no ≥20-char shared run after path stripping |
| 252 | 6d90f64f | exact_quote | b0b97bbf789ca1c3 | 5802d59e5bf227b7 | TP | ≥20-char match: '} from "@mariozechner/pi-tui";' |
| 253 | 767940c1 | exact_quote | 9c123db7bb11ec0a | dd78cda2281f6e43 | FP | short generic phrase (session persistence) |
| 254 | 767940c1 | exact_quote | 68b2ba1d116475f8 | dd78cda2281f6e43 | FP | no ≥20-char shared run after path stripping |
| 255 | f2a74003 | exact_quote | 9a4327d5621fd534 | 63873ca8e474f84d | FP | no ≥20-char shared run after path stripping |
| 256 | f2a74003 | exact_quote | 2ec668e8a8a71247 | 63873ca8e474f84d | FP | no ≥20-char shared run after path stripping |
| 257 | 0d9c4ae5 | file_discovery | 51630bacae67dc5f | c031e43d7b7105a0 | TP | truncated listing, same dir visible |
| 258 | 0d9c4ae5 | file_discovery | 51630bacae67dc5f | 53e826aa34a0d63d | TP | path in snippet |
| 259 | 2693f60b | file_discovery | af5a91c4657899f1 | 14a37791c1a822b8 | TP | path in snippet |
| 260 | 2693f60b | file_discovery | af5a91c4657899f1 | 1a8536547bf00491 | TP | path in snippet |
| 261 | 6e4a7b52 | file_discovery | 099b0642043b5c1a | ac17bca78e453b4b | TP | path in snippet |
| 262 | 6e4a7b52 | file_discovery | 54c086352d775c18 | fed230c1d319c54f | TP | truncated listing, same dir visible |
| 263 | 2c58149e | file_discovery | 72c3457ac1d7d07d | 71dc87a2c9d53dc2 | TP | path in snippet |
| 264 | 2c58149e | file_discovery | 7d299abc6190c000 | 3c799a86c194ffd9 | TP | truncated listing, same dir visible |
| 265 | 1b45e261 | file_discovery | 5fe4badab379e767 | e801bd13e569ed20 | TP | path in snippet |
| 266 | 1b45e261 | file_discovery | eb2d0669d2f3ccce | 9901096bee707ada | TP | path in snippet |
| 267 | 1b45e261 | file_discovery | eb2d0669d2f3ccce | 6c1d2eab8101908a | TP | path in snippet |
| 268 | 6c89caa7 | file_discovery | 1dad4168bd79cdde | 7d519895765afe38 | TP | path in snippet |
| 269 | 6c89caa7 | file_discovery | f9f4252dab96ff54 | 4e2ca99b49207246 | TP | path in snippet |
| 270 | 51bad63b | file_discovery | e66118c568511f1a | 077c433d2646e95f | TP | truncated listing, same dir visible |
| 271 | 51bad63b | file_discovery | 97c742c60421dc12 | a6105ab9c16ba6c3 | TP | path in snippet |
| 272 | 51bad63b | file_discovery | e66118c568511f1a | 67d58daf49da89a0 | TP | truncated listing, same dir visible |
| 273 | 2c58149e | file_discovery | 13f3d5e8d5aeb86f | 2b7e7cb21aff4525 | TP | path in snippet |
| 274 | f764d6fc | file_discovery | 3247719e055f98f7 | 54737e4ada09bbf9 | TP | path in snippet |
| 275 | f764d6fc | file_discovery | 41f239e4278e6fb5 | d651a472bc6824b1 | TP | path in snippet |
| 276 | b724a2e8 | file_discovery | e50de4b31240aee7 | ca97eec8029203a1 | TP | path in snippet |
| 277 | b60ddfde | file_discovery | bc7f4f4cc417ed3c | b0072a6a50e4259c | FP | listing top-level, .pi/themes/ not listed |
| 278 | b60ddfde | file_discovery | bc7f4f4cc417ed3c | 35bf656020077e8d | FP | listing top-level, .pi/agents/ not listed |
| 279 | b60ddfde | file_discovery | f70971826cfc422e | d26b9ac9be7f6f75 | TP | truncated listing, same dir visible |
| 280 | f8c8b590 | file_discovery | 69c6f0a64e95eec1 | 8a62f13958750861 | TP | path in snippet |
| 281 | f8c8b590 | file_discovery | 69c6f0a64e95eec1 | 8e5ec935b1f8e112 | TP | path in snippet |
| 282 | 4f26783b | file_discovery | 89d22d2570fa43b0 | 3e200fefa19787b9 | TP | path in snippet |
| 283 | f2a74003 | file_discovery | 90b7937ee04d6237 | cd33e3a60d880edd | TP | truncated listing, same dir visible |
| 284 | f2a74003 | file_discovery | a46577e34772bbbe | b37cb87b7e46806b | TP | path in snippet |
| 285 | 91404059 | file_discovery | 8dad73aa414ae701 | b85affd9737ad1bd | TP | path in snippet |
| 286 | 91404059 | file_discovery | 69f01fe6df20b6ec | 4a0213f6bb3afc63 | TP | path in snippet |
| 287 | 37e689ad | file_discovery | bbe87bf4c90d5ce5 | a279deaec74a8511 | TP | path in snippet |
| 288 | 37e689ad | file_discovery | bbe87bf4c90d5ce5 | cd5f4442a5c9d421 | TP | path in snippet |
| 289 | 614b39f0 | file_discovery | 5fed1f4401cc84ea | 8413d3019938c169 | TP | path in snippet |
| 290 | 614b39f0 | file_discovery | 5fed1f4401cc84ea | 1ea80d69eae2bf1a | TP | path in snippet |
| 291 | 61e2fc56 | file_discovery | a83908b542941048 | 20750c763faf9e82 | TP | path in snippet |
| 292 | 61e2fc56 | file_discovery | a83908b542941048 | 91e3bbb8d5be3507 | TP | path in snippet |
| 293 | 61e2fc56 | file_discovery | 35519ba4d3d6e6ad | 267a0a89ac105aae | TP | truncated listing, same dir visible |
| 294 | 0d9c4ae5 | file_discovery | ada1324e8aeaf9f3 | a73e7d347f8dc564 | TP | path in snippet |
| 295 | 0d9c4ae5 | file_discovery | ada1324e8aeaf9f3 | 4f0f53047c19c14d | TP | path in snippet |
| 296 | 7bb6d062 | file_discovery | 5a43eecf35efa628 | 9d38c578f44e91d2 | TP | path in snippet |
| 297 | 7bb6d062 | file_discovery | 5a43eecf35efa628 | dc998e26f1369049 | TP | path in snippet |
| 298 | 87443885 | file_discovery | fed65fe8b122e6c8 | d1159766e700ed4a | TP | path in snippet |
| 299 | 87443885 | file_discovery | f3ac68bfc6381d89 | 48326dc2bcff48da | TP | path in snippet |
| 300 | b724a2e8 | file_discovery | 220fb5135dfc3942 | efb8ddb2921068e0 | TP | path in snippet |
| 301 | b724a2e8 | file_discovery | 220fb5135dfc3942 | 45903379ee9cae17 | TP | path in snippet |
| 302 | d834f22c | file_discovery | 32a2de23c01a5d12 | 73aed82b70d1e88e | TP | truncated /src/core/ listing, providers/ plausible |
| 303 | d834f22c | file_discovery | dcb8397c0038e9ef | 154ab5bfbf007a4a | TP | path in snippet |
| 304 | f2a74003 | file_discovery | de7edc1b353d4fd3 | a5f1e43645f234cb | TP | truncated listing, same dir visible |
| 305 | f2a74003 | file_discovery | de7edc1b353d4fd3 | 0e55aaad4392b270 | TP | truncated listing, same dir visible |
| 306 | d834f22c | file_discovery | 0bd07f11a01ce2d8 | 08841e1da96e8e1e | TP | path in snippet |
| 307 | d834f22c | file_discovery | 0bd07f11a01ce2d8 | e104b3c0e397bec2 | TP | path in snippet |
| 308 | a54ddd36 | file_discovery | ce336afa6882f889 | 0f8beca0d34ba37f | TP | truncated listing, same dir visible |
| 309 | a54ddd36 | file_discovery | ce336afa6882f889 | 6de0e5310c370dfc | TP | truncated listing, dist/modes/ partially visible |
| 310 | 76086107 | file_discovery | 2c2eb480e235f3ba | 6f0739dbe7edc7bc | TP | truncated listing, same dir visible |
| 311 | 76086107 | file_discovery | 2c2eb480e235f3ba | c4fcb06c9d275b7b | TP | truncated listing, same dir visible |
| 312 | 76086107 | file_discovery | 2c2eb480e235f3ba | 23d9dba37730c8fb | TP | truncated listing, same dir visible |
| 313 | 2c58149e | file_discovery | a494bb4ad81f7fdb | f4a6af7e58f756b3 | FP | source is grep content output, not file listing |
| 314 | 2c58149e | file_discovery | 0af3c8157278a273 | fab91dc5572a87e4 | TP | path in snippet |
| 315 | 3998edcf | file_discovery | f21af8ff971b244a | 83fbccee4c621725 | TP | path in snippet |
| 316 | 3998edcf | file_discovery | f21af8ff971b244a | 045c799c3fdea543 | TP | truncated listing, dist/core/ visible |
| 317 | 3998edcf | file_discovery | f21af8ff971b244a | 6d82a04417bc86db | TP | path in snippet |
| 318 | b724a2e8 | file_discovery | aa47fedb6525c043 | 352a41b179f3edd8 | TP | path in snippet |
| 319 | b724a2e8 | file_discovery | aa47fedb6525c043 | 8b267cba904af46a | TP | path in snippet |
| 320 | 37e689ad | file_discovery | d2695b706789be4b | 9ae965403bdcf790 | TP | path in snippet |
| 321 | 37e689ad | file_discovery | d2695b706789be4b | 9074bcf25d6caf56 | TP | path in snippet |
| 322 | 37e689ad | file_discovery | 2e473267acca772c | 8b4c61851a7c0e52 | TP | path in snippet |
| 323 | 0d9c4ae5 | file_discovery | 2dee69ecbfd86402 | 16a08b3adde88d69 | TP | path in snippet |
| 324 | 0d9c4ae5 | file_discovery | 2dee69ecbfd86402 | bf3eaacb77db89af | TP | path in snippet |
| 325 | 51bad63b | file_discovery | 1068fd98824f65ef | e783f423a6c5b126 | TP | path in snippet |
| 326 | 51bad63b | file_discovery | 6e6307e28ee08306 | 37896dd43c2178fd | TP | path in snippet |
| 327 | 51bad63b | file_discovery | 1068fd98824f65ef | cfec63f2eabd182e | TP | path in snippet |
| 328 | 3c0b2ea8 | file_discovery | ed2292635239c72b | f78177db77eb7ae1 | TP | path in snippet |
| 329 | 3c0b2ea8 | file_discovery | 57fe5d1ef747e3c6 | a8953256f639fd37 | TP | path in snippet |
| 330 | e7296f54 | file_discovery | 88e72be0b478233b | 939142255d518cae | TP | path in snippet |
| 331 | 91404059 | file_discovery | 8be183369ec4918f | 488086ee7f82bd70 | TP | path in snippet |
| 332 | 91404059 | file_discovery | 8be183369ec4918f | 022522ed79093ba3 | TP | path in snippet |
| 333 | 91404059 | file_discovery | f4e95e375b96bae3 | 57962f955b7c3e43 | TP | truncated listing, same dir visible |
| 334 | 91404059 | file_discovery | f4e95e375b96bae3 | b2d0dbc178f5c6fc | FP | docs/ not visible in 11-file Glob result |
| 335 | 767940c1 | file_discovery | ea7ab66b74f51fa5 | 19368c86d5296d79 | TP | truncated listing, same dir visible |
| 336 | 767940c1 | file_discovery | ea7ab66b74f51fa5 | 12ea6e6f105cc875 | TP | truncated listing, same dir visible |
| 337 | f2a74003 | file_discovery | 0255cdc0de23059e | cfa2fcbfb585f24c | TP | path in snippet |
| 338 | f2a74003 | file_discovery | 0255cdc0de23059e | ad6851324fae03de | TP | path in snippet |

### FN candidates

| # | trace | tgt_seg | label | note |
| -: | ----- | ------- | ----- | ---- |
| 1 | 0d9c4ae5 | 8c07853df0ff8935 | correct_empty | assistant_text, no quotable predecessor |
| 2 | 0d9c4ae5 | 82bf2cb99d5c32e2 | correct_empty | no listing predecessor in neighborhood |
| 3 | 0d9c4ae5 | dacc531b01dc107e | correct_empty | bare dir target |
| 4 | 91404059 | 64f58ca1f62c0684 | missed | exact_quote should fire: parseFrontmatter type in tr, paraphrase in assistant_text |
| 5 | 91404059 | 99526dbe2bd3544e | correct_empty | assistant_text, no quotable predecessor |
| 6 | 91404059 | 1e9ef84ccbe08c6d | correct_empty | no listing predecessor in neighborhood |
| 7 | 91404059 | 5a7af0f2c03d6c21 | correct_empty | assistant_text, no quotable predecessor |
| 8 | 91404059 | b88c4370b929d2dc | correct_empty | no listing predecessor in neighborhood |
| 9 | 91404059 | d3d48864981325a6 | correct_empty | assistant_text, no quotable predecessor |
| 10 | 2693f60b | 412e21709cf1b296 | correct_empty | assistant_text, no quotable predecessor |
| 11 | 2693f60b | a6059a475814fd7f | correct_empty | assistant_text, no quotable predecessor |
| 12 | 2693f60b | 3100d85c464ef6f3 | correct_empty | assistant_text, no quotable predecessor |
| 13 | 6e4a7b52 | 06086c50bc835c4d | correct_empty | assistant_text, no quotable predecessor |
| 14 | 6e4a7b52 | cd580936e4ada0a9 | correct_empty | bare dir target |
| 15 | 6e4a7b52 | bd30ddebf422ee7a | correct_empty | no listing predecessor in neighborhood |
| 16 | 2c58149e | 055febf09e78dcef | correct_empty | no listing predecessor in neighborhood |
| 17 | 2c58149e | 3022f543dbc1a9df | correct_empty | assistant_text, no quotable predecessor |
| 18 | 2c58149e | af25444b10d5882f | correct_empty | no listing predecessor in neighborhood |
| 19 | 1b45e261 | c4028b90b9995f8b | correct_empty | no listing predecessor in neighborhood |
| 20 | 1b45e261 | f3a33bbbdb899f7d | correct_empty | assistant_text, no quotable predecessor |
| 21 | 1b45e261 | 48d07585ac391dbf | correct_empty | assistant_text, no quotable predecessor |
| 22 | 31a50fe9 | 5da69d9e9766247a | correct_empty | no listing predecessor in neighborhood |
| 23 | 31a50fe9 | b4dde3f162315e12 | correct_empty | bare dir target |
| 24 | 31a50fe9 | cf00902187a22bf6 | correct_empty | no listing predecessor in neighborhood |
| 25 | 6c89caa7 | 61fad1daf47f943e | correct_empty | assistant_text, no quotable predecessor |
| 26 | 6c89caa7 | 6c98395dfc54f3bf | correct_empty | no listing predecessor in neighborhood |
| 27 | 6c89caa7 | 8d62a3a1280b0a0e | correct_empty | assistant_text, no quotable predecessor |
| 28 | 8e690c72 | 6e2ab31fccf7e8de | correct_empty | no listing predecessor in neighborhood |
| 29 | 8e690c72 | 872db686512a9c7e | correct_empty | no listing predecessor in neighborhood |
| 30 | 8e690c72 | 4b13fe58841e3b69 | correct_empty | no listing predecessor in neighborhood |
| 31 | fb40f1b7 | 6a5dcf2d2e84d94d | correct_empty | bare dir target |
| 32 | fb40f1b7 | 7ee74f8ffe14a74b | correct_empty | assistant_text, no quotable predecessor |
| 33 | fb40f1b7 | e0d248dbd29279bf | correct_empty | no listing predecessor in neighborhood |
| 34 | c1ee68aa | afdc6236ab231b22 | correct_empty | no listing predecessor in neighborhood |
| 35 | c1ee68aa | ec097a7438084f39 | missed | exact_quote should fire: error path quoted verbatim from tr |
| 36 | c1ee68aa | 7e421504d1ef1e55 | correct_empty | no listing predecessor in neighborhood |
| 37 | 51bad63b | 981cefb9ab6e1dfa | correct_empty | no listing predecessor in neighborhood |
| 38 | 51bad63b | 6e5918668a7705a7 | correct_empty | no listing predecessor in neighborhood |
| 39 | 51bad63b | 09ee974dfbca6078 | correct_empty | bare dir target |
| 40 | 2c58149e | e74dd428c5e13cad | correct_empty | no listing predecessor in neighborhood |
| 41 | 2c58149e | 2345d4e778ab2ac6 | correct_empty | no listing predecessor in neighborhood |
| 42 | 2c58149e | 7c8fb409798e25f1 | correct_empty | no listing predecessor in neighborhood |
| 43 | f764d6fc | 059cbf4992795268 | correct_empty | bare dir target |
| 44 | f764d6fc | 21477c92655f1eb0 | correct_empty | bare dir target |
| 45 | f764d6fc | 318ed1b601625ece | correct_empty | no listing predecessor in neighborhood |
| 46 | b724a2e8 | 704c8bef66686dca | correct_empty | no listing predecessor in neighborhood |
| 47 | b724a2e8 | 6271d8edb7aa7fb1 | correct_empty | assistant_text, no quotable predecessor |
| 48 | b724a2e8 | 53b963791c090d6b | correct_empty | no listing predecessor in neighborhood |
| 49 | b60ddfde | 83fc30bbeabc58bf | correct_empty | bare dir target |
| 50 | b60ddfde | 586376dce97a646e | correct_empty | bare dir target |
| 51 | b60ddfde | 20230966a8ea915c | correct_empty | bare dir target |
| 52 | f8c8b590 | fc1c4b93a0ab4ed9 | correct_empty | no listing predecessor in neighborhood |
| 53 | f8c8b590 | 28ebc9ae52e3c813 | correct_empty | assistant_text, no quotable predecessor |
| 54 | f8c8b590 | 1d54cf16bb3c8623 | correct_empty | no listing predecessor in neighborhood |
| 55 | 6e4a7b52 | fd909ca517202295 | correct_empty | assistant_text, no quotable predecessor |
| 56 | 6e4a7b52 | 93c3628193a7d115 | correct_empty | no listing predecessor in neighborhood |
| 57 | 6e4a7b52 | 29c82661de1fb0a5 | correct_empty | no listing predecessor in neighborhood |
| 58 | c1ee68aa | 12a0aa3b508caa32 | correct_empty | assistant_text, no quotable predecessor |
| 59 | c1ee68aa | 974efd4af3c0a832 | correct_empty | assistant_text, no quotable predecessor |
| 60 | c1ee68aa | 9df8a106256e8526 | correct_empty | assistant_text, no quotable predecessor |
| 61 | 614b39f0 | 5112583e747c763e | correct_empty | assistant_text, no quotable predecessor |
| 62 | 614b39f0 | 6294ffd080aef62f | correct_empty | no listing predecessor in neighborhood |
| 63 | 614b39f0 | 4740e27a97ec3790 | correct_empty | assistant_text, no quotable predecessor |
| 64 | 4f26783b | dea78a73a2e6d502 | correct_empty | assistant_text, no quotable predecessor |
| 65 | 4f26783b | 7bd073b8564a449e | correct_empty | assistant_text, no quotable predecessor |
| 66 | 4f26783b | e646bb2a56ba06c8 | correct_empty | bare dir target |
| 67 | 4e2842a6 | 01c972033408fdb8 | correct_empty | no listing predecessor in neighborhood |
| 68 | 4e2842a6 | 090affec277527cb | correct_empty | assistant_text, no quotable predecessor |
| 69 | 4e2842a6 | f8caa5ad4277295b | correct_empty | assistant_text, no quotable predecessor |
| 70 | 7da7cd16 | 4f20620c3bca286b | correct_empty | assistant_text, no quotable predecessor |
| 71 | 7da7cd16 | 946c1a32bad952da | missed | exact_quote should fire: CHANGELOG entry text directly quoted |
| 72 | 7da7cd16 | 7d6b78f08c746569 | correct_empty | assistant_text, no quotable predecessor |
| 73 | f2a74003 | c7f7ff2ba8cf5782 | correct_empty | no listing predecessor in neighborhood |
| 74 | f2a74003 | 1fd1f2534c465a22 | correct_empty | no listing predecessor in neighborhood |
| 75 | f2a74003 | 6df61fe41bfe0486 | correct_empty | no listing predecessor in neighborhood |
| 76 | 31a50fe9 | c535916249990f22 | correct_empty | bare dir target |
| 77 | 31a50fe9 | da98a7e9edbee111 | correct_empty | no listing predecessor in neighborhood |
| 78 | 31a50fe9 | ee8cf9352809d304 | correct_empty | no listing predecessor in neighborhood |
| 79 | 91404059 | ece5e77a3e20bd66 | correct_empty | no listing predecessor in neighborhood |
| 80 | 91404059 | 3b1c2808ec8902d6 | correct_empty | assistant_text, no quotable predecessor |
| 81 | 91404059 | ae733dcc4a2fadf4 | correct_empty | assistant_text, no quotable predecessor |
| 82 | a54ddd36 | 8c73cfc484683d9d | correct_empty | no listing predecessor in neighborhood |
| 83 | a54ddd36 | 91c9313deebbff4d | correct_empty | assistant_text, no quotable predecessor |
| 84 | a54ddd36 | 7dd55d7043be2c94 | correct_empty | bare dir target |
| 85 | 37e689ad | 65459d3df94ee5b4 | correct_empty | assistant_text, no quotable predecessor |
| 86 | 37e689ad | 94845ce38fe465e4 | correct_empty | assistant_text, no quotable predecessor |
| 87 | 37e689ad | 61a8d16dfcff1b4a | correct_empty | assistant_text, no quotable predecessor |
| 88 | fb40f1b7 | cd5373562f9aa514 | correct_empty | bare dir target |
| 89 | fb40f1b7 | a90f981370458b0f | correct_empty | bare dir target |
| 90 | fb40f1b7 | cf73e8a973832052 | correct_empty | assistant_text, no quotable predecessor |
| 91 | 614b39f0 | 8e1c5bf6dbbd0d82 | correct_empty | assistant_text, no quotable predecessor |
| 92 | 614b39f0 | d134154f379a9bdb | missed | exact_quote should fire: build error fragment verbatim in assistant_text |
| 93 | 614b39f0 | fe7f1a79ad6d01cd | correct_empty | assistant_text, no quotable predecessor |
| 94 | 61e2fc56 | f01dfc02418af788 | correct_empty | bare dir target |
| 95 | 61e2fc56 | ea41353948c54b68 | correct_empty | bare dir target |
| 96 | 61e2fc56 | eea8d62548c13aa6 | correct_empty | bare dir target |
| 97 | cb9f58bd | e345af411fa0f151 | correct_empty | no listing predecessor in neighborhood |
| 98 | cb9f58bd | 0e64a782b59bc1f9 | correct_empty | no listing predecessor in neighborhood |
| 99 | cb9f58bd | 62ce3570c9025db4 | correct_empty | assistant_text, no quotable predecessor |
| 100 | 0d9c4ae5 | cea475344cccc8dc | correct_empty | no listing predecessor in neighborhood |
| 101 | 0d9c4ae5 | f1e417119c43c868 | correct_empty | assistant_text, no quotable predecessor |
| 102 | 0d9c4ae5 | baac9c6b21a719c1 | correct_empty | assistant_text, no quotable predecessor |
| 103 | 7bb6d062 | adae9112e1a5be8d | correct_empty | assistant_text, no quotable predecessor |
| 104 | 7bb6d062 | 9cfc5579095d13d0 | missed | exact_quote should fire: stash output discussed in assistant_text |
| 105 | 7bb6d062 | 809076263ad78476 | correct_empty | no listing predecessor in neighborhood |
| 106 | 87443885 | 858ad03efdee83e8 | correct_empty | assistant_text, no quotable predecessor |
| 107 | 87443885 | d0c42f6aceb2f1c8 | correct_empty | no listing predecessor in neighborhood |
| 108 | 87443885 | 25dc21af57cdf782 | correct_empty | assistant_text, no quotable predecessor |
| 109 | b724a2e8 | a8f791fcee3d8dd4 | correct_empty | assistant_text, no quotable predecessor |
| 110 | b724a2e8 | 8e3ee4e2d1f43461 | correct_empty | assistant_text, no quotable predecessor |
| 111 | b724a2e8 | 3030dbfcab253987 | correct_empty | assistant_text, no quotable predecessor |
| 112 | d834f22c | d69a8559c5da3966 | missed | exact_quote should fire: grep line-40 output verbatim in assistant_text |
| 113 | d834f22c | 152ebeb9994eb0ad | correct_empty | assistant_text, no quotable predecessor |
| 114 | d834f22c | 15c26fd68a0e0a3f | correct_empty | assistant_text, no quotable predecessor |
| 115 | f2a74003 | 4aaf7bd25616174d | correct_empty | no listing predecessor in neighborhood |
| 116 | f2a74003 | 6d4b02e02537e699 | correct_empty | bare dir target |
| 117 | f2a74003 | 51de01505006e644 | correct_empty | bare dir target |
| 118 | d834f22c | 74d1b408f4954386 | correct_empty | assistant_text, no quotable predecessor |
| 119 | d834f22c | 7b81abafe8f81769 | correct_empty | no listing predecessor in neighborhood |
| 120 | d834f22c | f1a6560e9072760e | correct_empty | bare dir target |
| 121 | a54ddd36 | c8512fe2237359f0 | correct_empty | no listing predecessor in neighborhood |
| 122 | a54ddd36 | 5373fe446cf86341 | correct_empty | bare dir target |
| 123 | a54ddd36 | 6ea73c77a4efa591 | correct_empty | assistant_text, no quotable predecessor |
| 124 | 9898f6d3 | 4b89929f50d8c9f0 | correct_empty | no listing predecessor in neighborhood |
| 125 | 9898f6d3 | 34a5f020e5955a0f | correct_empty | assistant_text, no quotable predecessor |
| 126 | 9898f6d3 | 4a8e4eac6a03b13a | correct_empty | no listing predecessor in neighborhood |
| 127 | 76086107 | 9790b2f595bbbe79 | correct_empty | bare dir target |
| 128 | 76086107 | a6c2b06bca8b75ad | correct_empty | no listing predecessor in neighborhood |
| 129 | 76086107 | 6ffe74c3e1b15713 | correct_empty | bare dir target |
| 130 | 37e689ad | 74c0077d2c52724c | correct_empty | bare dir target |
| 131 | 37e689ad | d7d3aa419f66d833 | correct_empty | assistant_text, no quotable predecessor |
| 132 | 37e689ad | 095a30b25164bfb1 | correct_empty | no listing predecessor in neighborhood |
| 133 | 2c58149e | 68915e9f5ca29507 | correct_empty | no listing predecessor in neighborhood |
| 134 | 2c58149e | 5b40365dbeddd1df | correct_empty | no listing predecessor in neighborhood |
| 135 | 2c58149e | e0f6be32b836f229 | correct_empty | assistant_text, no quotable predecessor |
| 136 | 3998edcf | 58447dd75631fb54 | correct_empty | assistant_text, no quotable predecessor |
| 137 | 3998edcf | 122060863bcb86e6 | correct_empty | bare dir target |
| 138 | 3998edcf | bd8dab7761b96d33 | correct_empty | bare dir target |
| 139 | b724a2e8 | 699ac6d35e20230a | correct_empty | no listing predecessor in neighborhood |
| 140 | b724a2e8 | eb1670c8cdaeb883 | correct_empty | assistant_text, no quotable predecessor |
| 141 | b724a2e8 | 51fa474f24eec0e4 | correct_empty | assistant_text, no quotable predecessor |
| 142 | 37e689ad | 21c12b401104cab1 | correct_empty | no listing predecessor in neighborhood |
| 143 | 37e689ad | be58236e8d2c541e | correct_empty | no listing predecessor in neighborhood |
| 144 | 37e689ad | 33f8ee9853d7c6bd | correct_empty | assistant_text, no quotable predecessor |
| 145 | 0d9c4ae5 | f62a3d2d77a0e79c | correct_empty | bare dir target |
| 146 | 0d9c4ae5 | 4b1752b06ec795e2 | correct_empty | no listing predecessor in neighborhood |
| 147 | 0d9c4ae5 | 0a269e4a110c0dd9 | correct_empty | bare dir target |
| 148 | 51bad63b | ff93ecf73e78b436 | correct_empty | bare dir target |
| 149 | 51bad63b | 5ff72a40c65cddca | correct_empty | bare dir target |
| 150 | 51bad63b | 8fbd110c804b2688 | correct_empty | no listing predecessor in neighborhood |
| 151 | 3c0b2ea8 | d7d97405d95a01e7 | correct_empty | no listing predecessor in neighborhood |
| 152 | 3c0b2ea8 | 24a8c8c1d6f31ea2 | correct_empty | no listing predecessor in neighborhood |
| 153 | 3c0b2ea8 | 77e7d1013bfd2865 | correct_empty | no listing predecessor in neighborhood |
| 154 | e7296f54 | 1f3bfea17305d538 | correct_empty | no listing predecessor in neighborhood |
| 155 | e7296f54 | fe77f1cd9733e07a | correct_empty | assistant_text, no quotable predecessor |
| 156 | e7296f54 | f4f3f358d8556f70 | correct_empty | no listing predecessor in neighborhood |
| 157 | 22f0b5a0 | 1af2e688cfc6b1e4 | correct_empty | assistant_text, no quotable predecessor |
| 158 | 22f0b5a0 | 250ad228dd07f15d | correct_empty | no listing predecessor in neighborhood |
| 159 | 22f0b5a0 | 47558a5a221c888c | correct_empty | no listing predecessor in neighborhood |
| 160 | cb9f58bd | c6a19554ae8f28c1 | correct_empty | assistant_text, no quotable predecessor |
| 161 | cb9f58bd | 0ad63c690a373d6e | correct_empty | assistant_text, no quotable predecessor |
| 162 | cb9f58bd | 6578a4464b070699 | correct_empty | assistant_text, no quotable predecessor |
| 163 | 91404059 | 2e2f6d4332fd47c7 | correct_empty | bare dir target |
| 164 | 91404059 | 79c578bc0dd989d2 | correct_empty | bare dir target |
| 165 | 91404059 | 6db2e79ed5a39ec4 | correct_empty | bare dir target |
| 166 | 91404059 | 856bbd0e40590ea2 | correct_empty | no listing predecessor in neighborhood |
| 167 | 91404059 | a2f8b53e86d42011 | correct_empty | no listing predecessor in neighborhood |
| 168 | 91404059 | d67d70fe9e43d43e | correct_empty | assistant_text, no quotable predecessor |
| 169 | 44d85a2d | e80db7dba1795786 | correct_empty | assistant_text, no quotable predecessor |
| 170 | 44d85a2d | 6a724fe5b8b4f5c1 | correct_empty | no listing predecessor in neighborhood |
| 171 | 44d85a2d | fec69a229840b250 | correct_empty | assistant_text, no quotable predecessor |
| 172 | 6d90f64f | d5df64816ffe5165 | correct_empty | assistant_text, no quotable predecessor |
| 173 | 6d90f64f | 28939b73e496f546 | correct_empty | bare dir target |
| 174 | 6d90f64f | 310207764bad8263 | correct_empty | no listing predecessor in neighborhood |
| 175 | 767940c1 | b92265c75b3e9a01 | correct_empty | no listing predecessor in neighborhood |
| 176 | 767940c1 | c6b78585f91fc580 | correct_empty | no listing predecessor in neighborhood |
| 177 | 767940c1 | ba861fd896805337 | correct_empty | bare dir target |
| 178 | f2a74003 | 6b9e1a0bf3bc6531 | correct_empty | no listing predecessor in neighborhood |
| 179 | f2a74003 | 1514cf60c99e0927 | correct_empty | no listing predecessor in neighborhood |
| 180 | f2a74003 | 68062bc6a56a1c82 | correct_empty | assistant_text, no quotable predecessor |

## Failure-mode breakdown (FPs only)

### file_reread FPs

| failure reason | count |
| -------------- | ----: |
| empty result (no path evidence) | 5 |
| tool error source | 4 |
| path mismatch / overflow | 1 |

### exact_quote FPs

| failure reason | count |
| -------------- | ----: |
| no ≥20-char common run after path stripping | 88 |
| heredoc write-through boilerplate | 2 |
| cross-doc architecture boilerplate | 2 |
| generic boilerplate | 2 |

### file_discovery FPs

| failure reason | count |
| -------------- | ----: |
| path not in snippet (wrong dir or not listed) | 2 |
| source is grep content, not listing | 1 |
| other | 1 |

## Missed-edge breakdown (FNs only)

All 6 missed edges are exact_quote misses — the exact_quote rule did not fire when
a tool_result contained content that the immediately following assistant_text directly quoted or closely paraphrased.
The likely cause is that the shared token did not meet the ≥8-char gating threshold after ambient filtering,
or the content was from a Bash tool_result whose output triggered a source-guard false filter.

| missed-ref type | count |
| --------------- | ----: |
| exact_quote should have fired (tr content → assistant_text paraphrase/quote) | 6 |
| discovery-by-listing (file_discovery should have fired) | 0 |
| cross-turn paraphrase (no matching rule) | 0 |
| other | 0 |