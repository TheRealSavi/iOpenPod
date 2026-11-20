// Repack reviewed modules while preserving the fixed native startup anchors.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"github.com/freemyipod/wInd3x/pkg/efi"
	"os"
	"path/filepath"
)

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func replace(s efi.Section, raw []byte) int {
	if s.Header().Type == efi.SectionTypePE32 {
		s.SetRaw(raw)
		return 1
	}
	n := 0
	for _, sub := range s.Sub() {
		if sub.Section != nil {
			n += replace(sub.Section, raw)
		}
	}
	return n
}
func digest(b []byte) string { return fmt.Sprintf("%x", sha256.Sum256(b)) }

type profile struct {
	StockSHA      string `json:"stock_sha256"`
	ROMOffset     int    `json:"rom_offset"`
	PadOffset     int    `json:"pad_offset"`
	SecCoreOffset int    `json:"seccore_offset"`
	Shared        bool   `json:"shared"`
}

func padFile(raw []byte, size int) []byte {
	// Preserve the occupied eight-byte FFS span, not the old unaligned size.
	// If the serialized replacement already occupies it, ordinary FFS alignment
	// suffices and inserting an extra Raw section would itself overflow the span.
	if (len(raw)+7)&^7 == (size+7)&^7 {
		return raw
	}
	for len(raw)%4 != 0 {
		raw = append(raw, 0)
	}
	gap := size - len(raw)
	if gap < 4 {
		panic(fmt.Sprintf("no room for bounded raw section: serialized=%d target=%d gap=%d", len(raw), size, gap))
	}
	pad := make([]byte, gap)
	pad[0] = byte(gap)
	pad[1] = byte(gap >> 8)
	pad[2] = byte(gap >> 16)
	pad[3] = byte(efi.SectionTypeRaw)
	raw = append(raw, pad...)
	raw[20] = byte(size)
	raw[21] = byte(size >> 8)
	raw[22] = byte(size >> 16)
	state := raw[23]
	raw[16] = 0
	raw[17] = 0
	raw[23] = 0
	var sum byte
	for _, b := range raw[:24] {
		sum += b
	}
	raw[16] = -sum
	raw[23] = state
	if raw[19]&0x40 != 0 {
		sum = 0
		for _, b := range raw[24:] {
			sum += b
		}
		raw[17] = -sum
	} else {
		raw[17] = 0xaa
	}
	return raw
}
func main() {
	if len(os.Args) != 4 {
		panic("repack ORIGINAL_LOADER OUTPUT_DIRECTORY PROFILE_JSON")
	}
	old, err := os.ReadFile(os.Args[1])
	must(err)
	out := os.Args[2]
	config, err := os.ReadFile(os.Args[3])
	must(err)
	var p profile
	must(json.Unmarshal(config, &p))
	if len(old) != 0x1f800 || digest(old) != p.StockSHA {
		panic("unqualified loader")
	}
	v, err := efi.ReadVolume(efi.NewNestedReader(old[0x100:]))
	must(err)
	modified := map[string]string{"773641a1-cc51-41b7-b121-943bd7c5fc3f": "ROM-unsigned.pe32", "2ed6d875-3da4-462c-b201-7c557027a5ba": "Bds-unsigned.pe32"}
	if p.Shared {
		modified["0e2bee84-a47c-4d0c-8271-97f42cdbcc76"] = "SoftwareVersion-shared.pe32"
		modified["a3f1a310-0ad9-42e3-8918-3c81d2e3008c"] = "ImageManagerSecurity-shared.pe32"
	}
	result := append([]byte{}, old[:0x148]...)
	changes := []map[string]interface{}{}
	changed := 0
	for _, f := range v.Files {
		start := 0x100 + f.ReadOffset
		length := int(f.Size.Uint32())
		padded := (length + 7) &^ 7
		at := len(result)
		raw := append([]byte{}, old[start:start+padded]...)
		compensating := p.Shared && f.GUID.String() == "a3f1a310-0ad9-42e3-8918-3c81d2e3008c"
		if start <= p.ROMOffset && at != start && !compensating {
			panic("an early or ROM file moved")
		}
		if name, ok := modified[f.GUID.String()]; ok {
			pe, err := os.ReadFile(filepath.Join(out, name))
			must(err)
			n := 0
			for _, s := range f.Sections {
				n += replace(s, pe)
			}
			if n != 1 {
				panic("expected one replacement PE")
			}
			raw, err = f.Serialize()
			must(err)
			changed++
			if name != "ROM-unsigned.pe32" && !(p.Shared && name == "Bds-unsigned.pe32") {
				raw = padFile(raw, length-(at-start))
			}
			for len(raw)%8 != 0 {
				raw = append(raw, 0xff)
			}
		} else if f.FileType == efi.FileTypePadding {
			if start != p.PadOffset || length != p.SecCoreOffset-p.PadOffset {
				panic("unexpected padding")
			}
			left := p.SecCoreOffset - at
			if left < 24 || left%8 != 0 {
				panic("insufficient fixed-span free space")
			}
			f.Size = efi.ToUint24(uint32(left))
			raw, err = f.Serialize()
			must(err)
		} else if f.FileType == efi.FileTypeSecurityCore && (at != start || start != p.SecCoreOffset) {
			panic("SecCore moved")
		}
		result = append(result, raw...)
		changes = append(changes, map[string]interface{}{"guid": f.GUID.String(), "old_offset": start, "new_offset": at, "bytes": len(raw), "unchanged_bytes": bytes.Equal(raw, old[start:start+padded])})
	}
	if changed != len(modified) || len(result) != len(old) || !bytes.Equal(result[:0x148], old[:0x148]) || !bytes.Equal(result[p.SecCoreOffset:], old[p.SecCoreOffset:]) {
		panic("fixed loader framing changed")
	}
	parsed, err := efi.ReadVolume(efi.NewNestedReader(result[0x100:]))
	must(err)
	if len(parsed.Files) != len(v.Files) {
		panic("file count changed")
	}
	extracted := map[string]string{}
	var collect func(efi.Section, string)
	collect = func(s efi.Section, guid string) {
		if s.Header().Type == efi.SectionTypePE32 {
			extracted[guid] = digest(s.Raw())
			must(os.WriteFile(filepath.Join(out, "extracted-"+guid+".pe32"), s.Raw(), 0600))
		}
		for _, sub := range s.Sub() {
			if sub.Section != nil {
				collect(sub.Section, guid)
			}
		}
	}
	for i, f := range parsed.Files {
		if f.GUID != v.Files[i].GUID {
			panic("FFS order changed")
		}
		for _, s := range f.Sections {
			collect(s, f.GUID.String())
		}
	}
	for guid, name := range modified {
		p, err := os.ReadFile(filepath.Join(out, name))
		must(err)
		if extracted[guid] != digest(p) {
			panic("replacement failed independent decompression")
		}
	}
	must(os.WriteFile(filepath.Join(out, "loader-body.bin"), result, 0600))
	report := map[string]interface{}{"source_sha256": digest(old), "sha256": digest(result), "bytes": len(result), "files": changes, "extracted_pe_sha256": extracted, "fixed_seccore_offset": p.SecCoreOffset}
	j, err := json.MarshalIndent(report, "", "  ")
	must(err)
	must(os.WriteFile(filepath.Join(out, "repack.json"), j, 0600))
	fmt.Printf("Repacked %d FFS files; fixed SecCore; loader SHA256 %s\n", len(parsed.Files), digest(result))
}
