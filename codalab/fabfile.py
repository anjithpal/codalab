import os,sys,datetime,tempfile
from fabric.operations import local as lrun, run, put
from fabric.api import env, task, hosts, roles, cd, shell_env, sudo, lcd, settings, prefix
from fabric.contrib.files import exists
from fabvenv import make_virtualenv, virtualenv

pathjoin = lambda *args: os.path.join(*args).replace("\\", "/")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PATH = os.path.join(THIS_DIR,'venv')
THIS_SETTINGS_DIR = pathjoin(THIS_DIR,'codalab','settings')

@task
def set_env(**kwargs):
    env.repo_tag = 'master'
    env.REMOTE_USER = env.user
    env.DEPLOY_USER = env.user
    env.DEPLOY_PATH = 'codalab'
    env.CONFIG_GEN_PATH = pathjoin(env.DEPLOY_PATH,'codalab','config','generated')
    env.REPO_URL = 'https://github.com/codalab/codalab.git'
    env.venvpath = pathjoin('/home',env.DEPLOY_USER,'venv')

# Environment variables will take precidence
try:
    env.DJANGO_CONFIG
except AttributeError:
    env.DJANGO_CONFIG = 'Dev'
try:
    env.SETTINGS_MODULE
except AttributeError:
    env.SETTINGS_MODULE = 'codalab.settings'
set_env()



sys.path.append('.')

os.environ.setdefault("DJANGO_SETTINGS_MODULE", env.SETTINGS_MODULE)
os.environ.setdefault('DJANGO_CONFIGURATION', env.DJANGO_CONFIG)

env.django_configuration = os.environ['DJANGO_CONFIGURATION']
env.django_settings_module = os.environ['DJANGO_SETTINGS_MODULE']

#from fabric.contrib import django

#from configurations import importer
#importer.install()

#django.settings_module(env.django_settings_module)
#from django.conf import settings as django_settings

env.EXTERNAL_SITE_CONFIG = False

    
@task
def repotag(name='master'):
    env.repo_tag = name
        
@task
def site_config(path=None,url=None,module=None):
    spath = 'src'
    if path and os.path.exists(path):
        path = os.path.abspath(path)
    elif module:
        mod = __import__(module)
        if os.path.isdir(mod.__path__[0]):
            path = mod.__path__[0]
        else:
            raise Exception("Must be a directory module")
    with settings(warn_ony=True),lcd(path):
        res = lrun('git diff --exit-code')
        if res.return_code != 0:
            raise Exception("*** Module has local changes. You must commit them.")
        tmp = tempfile.mkdtemp()
        fname = 'latest_msr_config.tar.gz'
        tmpf =  os.path.join(tmp,fname)
        path = path.rstrip('/')
        lrun('git archive --prefix=%s%s -o %s HEAD' % (os.path.basename(path),os.path.sep,tmpf))
    env.run('mkdir -p %s' % spath)
    put(tmpf)
    env.run('tar -C %s -xvzf %s' % (spath,fname))
    with virtualenv(env.venvpath), cd(spath):       
        env.run('pip install -U --force-reinstall ./%s' % os.path.basename(path))
    env.EXTERNAL_SITE_CONFIG = True

@task
def local(**kwargs):
    set_env(**kwargs) 
    env.run = lrun
    
@task
def remote(**kwargs):    
    set_env(**kwargs)
    env.run = run
   
@task
def clone_repo(url=env.REPO_URL,target=env.DEPLOY_PATH):
    env.run("git clone %s %s" % (url, target))
   
@task
def provision():
    """
    This will copy the provision script from the repo and execute it.
    """
    env.run('rm -rf codalab_scripts/*')
    env.run('mkdir -p codalab_scripts')
    put(pathjoin(THIS_DIR,'scripts/ubuntu/'), 'codalab_scripts/')
    env.run('chmod a+x codalab_scripts/ubuntu/provision')
    sudo('codalab_scripts/ubuntu/provision %s' % env.DEPLOY_USER)

@task
def config_gen(config=None,settings_module=None):
    with shell_env(DJANGO_CONFIGURATION=config,DJANGO_SETTINGS_MODULE=settings_module):
        env.run('python manage.py config_gen')

@task
def bootstrap():    
    make_virtualenv(path=env.venvpath, system_site_packages=False)
    #run('virtualenv --distribute %s' % env.venvpath)
    #with prefix('source %s' % os.path.join(env.venvpath, 'bin/activate')):
    env.run('killall supervisord')
    with virtualenv(env.venvpath):
        env.run('pip install --upgrade pip')
        env.run('pip install --upgrade Distribute')
        if exists(env.DEPLOY_PATH):
            env.run('mv %s %s' %  (env.DEPLOY_PATH, env.DEPLOY_PATH + '_' + str(datetime.datetime.now().strftime('%Y%m%d%s%f'))))
            #sudo('rm -rf %s' % env.DEPLOY_PATH)
        clone_repo(target=env.DEPLOY_PATH)


@task
def update_to_tag(tag=None):
    env.run('git checkout %s' % tag)

@task
def start_supervisor():
    env.run('supervisord -c %s' % pathjoin(env.CONFIG_GEN_PATH,'supervisor.conf'))

@task
def restart_supervisor():
    with virtualenv(env.venvpath),cd(env.DEPLOY_PATH):
        if not exists('codalab/var/supervisord.pid', verbose=True):
            env.run('./supervisor')
        else:
            env.run('./supervisorctl update')
            env.run('./supervisorctl restart all')

@task
def update():
    with virtualenv(env.venvpath):
        with cd(env.DEPLOY_PATH):
            env.run('git pull')
            update_to_tag(tag=env.repo_tag)
            requirements()          
            with cd('codalab'):
                config_gen(config=env.django_configuration,settings_module=env.django_settings_module)
                env.run('./manage syncdb --noinput')
                # When South is enabled
                #env.run('./manage migrate')
                env.run('./manage collectstatic --noinput')
            
@task
def requirements():
    env.run('./requirements dev.txt azure.txt nix.txt')
            

@task
def initialize_brats():
    with virtualenv(env.venvpath),cd(env.DEPLOY_PATH):
        env.run('codalab/scripts/init.sh')
