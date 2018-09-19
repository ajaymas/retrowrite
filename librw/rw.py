import argparse
from capstone import CS_OP_IMM, CS_GRP_JUMP, CS_GRP_CALL, CS_OP_MEM


class Rewriter():
    GCC_FUNCTIONS = [
        "_start",
        "__libc_start_main",
        "__libc_csu_fini",
        "__libc_csu_init",
        "__lib_csu_fini",
        "_init",
        "__libc_init_first",
        "_fini",
        "_rtld_fini",
        "_exit",
        "__get_pc_think_bx",
        "__do_global_dtors_aux",
        "__gmon_start",
        "frame_dummy",
        "__do_global_ctors_aux",
        "atexit",
        "__register_frame_info",
        "deregister_tm_clones",
        "register_tm_clones",
        "__do_global_dtors_aux",
        "__frame_dummy_init_array_entry",
        "__init_array_start",
        "__do_global_dtors_aux_fini_array_entry",
        "__init_array_end",
        "__stack_chk_fail",
        "__cxa_atexit",
        "__cxa_finalize",
    ]

    DATASECTIONS = [".rodata", ".data", ".bss", ".data.rel.ro", ".init_array"]

    def __init__(self, container, outfile):
        self.container = container
        self.outfile = outfile

        for sec, section in self.container.sections.items():
            section.load()

        for _, function in self.container.functions.items():
            if function.name in Rewriter.GCC_FUNCTIONS:
                continue
            function.disasm()

    def symbolize(self):
        symb = Symbolizer()
        symb.symbolize_text_section(self.container, None)

    def dump(self):
        results = list()
        for sec, section in self.container.sections.items():
            results.append("%s" % (section))

        results.append(".section .text")
        results.append(".align 16")

        for _, function in self.container.functions.items():
            if function.name in Rewriter.GCC_FUNCTIONS:
                continue
            results.append("%s" % (function))

        with open(self.outfile, 'w') as outfd:
            outfd.write("\n".join(results))


class Symbolizer():
    JUMPS = [
        "jmp",
        "jo",
        "jno",
        "js",
        "jns",
        "je",
        "jz",
        "jne",
        "jnz",
        "jb",
        "jbe",
        "jnae",
        "jc",
        "jnb",
        "jae",
        "jnc",
        "jna",
        "ja",
        "jae",
        "jnbe",
        "jl",
        "jnge",
        "jge",
        "jnl",
        "jle",
        "jng",
        "jg",
        "jnle",
        "jp",
        "jpe",
        "jnp",
        "jpo",
        "jcxz",
        "jecxz",
    ]

    def __init__(self):
        pass

    # TODO: Use named symbols instead of generic labels when possible.
    # TODO: Replace generic call labels with function names instead
    def symbolize_text_section(self, container, context):
        # Symbolize using relocation information.
        for rel in container.relocations[".text"]:

            fn = container.function_of_address(rel['offset'])
            if not fn or fn.name in Rewriter.GCC_FUNCTIONS:
                continue

            inst = fn.instruction_of_address(rel['offset'])
            if not inst:
                continue

            # Fix up imports
            if rel['st_value'] == 0 and "@@" in rel['name']:
                if len(inst.cs.operands) == 1:
                    inst.op_str = "%s@PLT" % (rel['name'].split("@")[0])
                else:
                    # Figure out which argument needs to be
                    # converted to a symbol.
                    mem_access, idx = inst.get_mem_access_op()
                    if not mem_access:
                        continue
                    value = hex(mem_access.disp)
                    inst.op_str = inst.op_str.replace(
                        value, rel['name'].split("@")[0])
            else:
                mem_access, idx = inst.get_mem_access_op()
                if not mem_access:
                    # These are probably calls?
                    continue
                value = hex(mem_access.disp)
                inst.op_str = inst.op_str.replace(value,
                                                  ".LC%x" % (rel['st_value']))

        self.symbolize_cf_transfer(container, context)

    def symbolize_cf_transfer(self, container, context=None):
        for _, function in container.functions.items():
            for instruction in function.cache:
                if (CS_GRP_JUMP not in instruction.cs.groups
                        and CS_GRP_CALL not in instruction.cs.groups):
                    continue

                if instruction.cs.operands[0].type == CS_OP_IMM:
                    target = instruction.cs.operands[0].imm
                    # Check if the target is in .text section.
                    if container.is_in_section(".text", target):
                        function.bbstarts.add(target)
                        instruction.op_str = ".L%x" % (target)

    def symbolize_data_sections(self, container, context=None):
        pass


if __name__ == "__main__":
    from loader import Loader

    argp = argparse.ArgumentParser()

    argp.add_argument("bin", type=str, help="Input binary to load")
    argp.add_argument("outfile", type=str, help="Symbolized ASM output")

    argp.add_argument(
        "--flist", type=str, help="Load function list from .json file")

    args = argp.parse_args()

    loader = Loader(args.bin)

    flist = loader.flist_from_symtab()
    loader.load_functions(flist)

    slist = loader.slist_from_symtab()
    loader.load_data_sections(slist, lambda x: x in Rewriter.DATASECTIONS)

    reloc_list = loader.reloc_list_from_symtab()
    loader.load_relocations(reloc_list)

    loader.container.attach_loader(loader)

    rw = Rewriter(loader.container, args.outfile)
    rw.symbolize()
    rw.dump()