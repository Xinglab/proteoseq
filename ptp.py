#! /u/home/y/ybwang/python

from optparse import OptionParser
from collections import defaultdict
import os,sys,random,datetime,warnings,re
import logging
import subprocess

BINDIR = '/u/home/y/ybwang/nobackup-yxing-PROJECT/ProteoTranscriptomePipeline/bin'
OUTDIR = 'outdir'

def main():
	global OUTDIR
	usage = 'usage: %prog <options> -b Aligned.out.sorted.bam -j SJ.tab.out -p proteomicsdir -e HSExonfile -o outdir --l 66 --g genome_file --min-junc-reads 2 --trim-RK False'
	parser = OptionParser(usage)
	# necessary parameters
	parser.add_option('-b','--bamfile', dest='bamfile', help='bam file from STAR [Default %default]')
	parser.add_option('-j','--sjfile', dest='sjfile', help='SJ.tab.out file from STAR [Default %default]')
	parser.add_option('-p','--rawdir', dest='rawdir', help='proteomics dir (format: raw/mzXML) [Default %default]')
	parser.add_option('-e','--exonfile', dest='exonfile', help='exons file (bed format) [Default %default]')
	parser.add_option('-o', dest='outdir',default=OUTDIR, help='Output dir filename [Default %default]')	
	# parameters for translation
        parser.add_option('--l', dest='flank', type='int', default=66, help='Extend flanking junction ends by this number of bp [Default %default]')
        parser.add_option('--g', dest='genome_file', default='/u/home/f/frankwoe/nobackup/hg19/hg19_by_chrom/', help='genomic fasta directory (by chromosomes) [Default %default]')
        parser.add_option('--min-junc-reads', dest='min_junc_reads', default=2, type='int', help='Minimum number of reads required spanning the junction [Default %default]')
	(options, args) = parser.parse_args()
	# check parameters
	if options.sjfile is None or options.bamfile is None or options.exonfile is None or options.rawdir is None:
		sys.exit("[ERROR] "+parser.get_usage())
	if options.outdir is not None:
		OUTDIR = re.sub(re.compile("/$"),"",options.outdir)

	# mkdir 'tmp' if not exists
	if not os.path.exists(OUTDIR):
		os.makedirs(OUTDIR)
	warnings.formatwarning = custom_formatwarning
	logging.basicConfig(filename=OUTDIR+'/pipeline.log', level=logging.INFO)

	## start
	# 1. parse SJ.tab.out file
	warnings.warn("## starting parse junction files")
	filename = parseSJ(options.sjfile)
	warnings.warn('## output file name: %s' % filename.replace('.SJ',''))
	# 2. translate junctions to peptide
	warnings.warn("## starting translating into junction peptides")
	fastaname = translate(options.bamfile,OUTDIR+"/"+filename,options.exonfile,options.flank,options.genome_file,options.min_junc_reads,OUTDIR+"/"+filename.replace('SJ','fa'))
	# 3. merge peptides to uniprot database
	customdb = mergePeps2Database(fastaname)
	# 4. database search using comet
	cometoutdir = databaseSearch(options.rawdir, OUTDIR+"/"+customdb)
	# 5. percolator (crux percolator)
	percolatorfile = percolatorCrux(cometoutdir)
	# 6. post-filter(extract peptide mapped Alu/HSE exons, and FDR filter)
	postPercolatorFilter(OUTDIR+'/'+fastaname,percolatorfile,options.exonfile,options.sjfile)

def test(outdir,outfile):
	global OUTDIR
	OUTDIR = outdir
	fastaname = outdir+'/'+outfile+'.fa'
	sjfile = 'data/SJ_out/LCLs/GM18486.rna.SJ'
	customdb = outdir+'/merge_'+outfile+'.fa'
	cometoutdir = 'comet_'+outfile
	percolatorCrux(cometoutdir)
	percolatorfile = outdir + '/cruxoutput_' + outfile + '/percolator.target.peptides.txt'
	exonfile = 'data/Ensembl_Alu_25bp_0.5.unique.sorted.bed'
	postPercolatorFilter(fastaname,percolatorfile,exonfile,sjfile)
	
def parseSJ(SJfile):
	if os.path.exists(SJfile) == False:
		sys.exit("[ERROR]: Junction file not exists!\n")
	outfile = datetime.datetime.now().strftime('%Y%m%d%H%M%S') + "-" + str(random.randint(1000,9999)) + ".SJ"
	os.system("python "+BINDIR+"/"+"parse_SJ.py " + SJfile + " " + OUTDIR+ "/" + outfile)
	return os.path.basename(outfile)

def translate(bamfile,sjfile,exonfiles,flank,genome_file,min_junc_reads,outfile):
	if os.path.exists(bamfile) == False:
		sys.exit("[ERROR]: Bam file not exists!\n")
	cmd = "python "+BINDIR+"/"+"translateJunc-star.py -o " + outfile + " -l " + str(flank) + " --min-junc-reads=" + str(min_junc_reads) + " -g " + genome_file + " " + bamfile + " " + sjfile + " " + exonfiles
	os.system(cmd)
	return os.path.basename(outfile)

def mergePeps2Database(fastafile):
	os.system("cat /u/home/y/ybwang/nobackup-yxing-PROJECT/ProteoTranscriptomePipeline/data/UP000005640_9606_additional_cdhit1.fasta " + OUTDIR+"/"+fastafile + ">" + OUTDIR + "/merge_" + fastafile)
	return os.path.basename(OUTDIR + "/merge_" + fastafile)

def databaseSearch(rawdir, database):
	WINE = "/u/home/y/ybwang/comet/wine"
	COMET = BINDIR + '/'+"comet.2015025.win64.exe"
	PARA = BINDIR + "/"+ "comet.params.high-low"
	COMETDIR = OUTDIR + "/comet_" + re.sub(re.compile("merge_|\.fa$"),"",os.path.basename(database))
	RAWDIR = re.sub(re.compile("/$"),"",rawdir)
	mylogger = logging.getLogger("comet")

	allfiles = os.listdir(RAWDIR)
	rawfiles = [x for x in allfiles if re.search('\.raw|\.mzXML',x) is not None]
	if not os.path.exists(COMETDIR):
		os.makedirs(COMETDIR)
	for i in rawfiles[0:]:
		inf = RAWDIR + '/' + i
		outf = COMETDIR + '/' + re.sub(re.compile("\..*$"),"",i)
		cmd = "WINEDEBUG=fixme-all,err-all " + WINE +" "+ COMET +" -P"+ PARA+" -D"+database+" -N"+outf+" "+inf
		p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		for line in p.stdout.readlines():
			mylogger.info(line.rstrip())
		retval = p.wait()
	return os.path.basename(COMETDIR)

def percolatorCrux(cometdir):
	cometfiles = os.listdir(OUTDIR+'/'+cometdir)
	cruxPrecTmp = OUTDIR+'/'+cometdir.replace('comet','cruxPrecTmp')	
	cruxoutdir = OUTDIR+'/'+cometdir.replace('comet','cruxoutput')
	if not os.path.exists(cruxoutdir):
                os.makedirs(cruxoutdir)
	os.system(BINDIR+'/modifyScanNr2CruxPerc.py'+' '+OUTDIR+'/'+cometdir +' '+cruxPrecTmp)
	os.system(BINDIR+'/crux percolator --train-fdr 0.05 --test-fdr 0.05 --overwrite T --output-dir ' + cruxoutdir + ' ' + cruxPrecTmp + '/' + cometdir + '.2cruxprec')
	return cruxoutdir + '/percolator.target.peptides.txt'
	

def postPercolatorFilter(fastaname,percolatorfile,exonfille,sjfile, threadNum=1):
	tmpdir = OUTDIR+'/tmp'
	os.system(BINDIR+'/cruxpep_percolator_test2parellel.py -p %s -c %s -e %s -j %s -t %s -n %d' % (fastaname,percolatorfile,exonfille,sjfile,tmpdir,threadNum))

def custom_formatwarning(msg, *a):
	# ignore everything except the message
	return str(msg) + '\n'

if __name__ == '__main__':
	main()
	#test(sys.argv[1],sys.argv[2])
